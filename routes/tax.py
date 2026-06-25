"""
routes/tax.py — 주식 세금 계산기 API + 페이지.

계산 항목:
  - 증권거래세: 매도금액 × 0.20% (KOSPI/KOSDAQ 동일, 농특세 포함)
  - 배당소득세: 배당금 × 15.4% (소득세 14% + 지방소득세 1.4%)
  - 양도소득세: 소액주주 비과세(현행법), 표시만
  - 순수익: 실현손익 - 증권거래세

데이터 소스: stock_transactions 테이블 (매수/매도 기록)
"""
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from database.db_connection import get_db_connection
from routes.utils import require_login, api_require_login, get_user_no
from templates_config import render

router = APIRouter()

TRANSACTION_TAX_RATE = 0.002   # 증권거래세 0.20%
DIVIDEND_TAX_RATE    = 0.154   # 배당소득세 15.4%


@router.get("/stock_tax", dependencies=[Depends(require_login)])
def tax_page(request: Request):
    return render(request, "stock/tax.html")


@router.post("/api/tax/calculate", dependencies=[Depends(api_require_login)])
def tax_calculate(body: dict = Body(default={})):
    """단건 매매 세금/수수료 계산기 (React Tax.jsx 계약).
    - 증권거래세 0.20% (매도금액), 유관기관제비용 0.0036396% (양방)
    - 수수료 0.015% (양방, 일반 온라인 기준)
    - 양도소득세: 소액주주 국내상장 비과세 / 대주주 22% (과세표준 3억 이하, 단순화)
    """
    try:
        buy_price  = float(body.get('buy_price') or 0)
        sell_price = float(body.get('sell_price') or 0)
        quantity   = int(body.get('quantity') or 0)
        is_major   = bool(body.get('is_major_shareholder'))
    except (ValueError, TypeError):
        return JSONResponse({"error": "숫자 입력값을 확인하세요."}, status_code=400)
    if buy_price <= 0 or sell_price <= 0 or quantity <= 0:
        return JSONResponse({"error": "매수가/매도가/수량을 모두 입력하세요."}, status_code=400)

    buy_total  = buy_price * quantity
    sell_total = sell_price * quantity

    transaction_tax = sell_total * TRANSACTION_TAX_RATE          # 증권거래세 (매도)
    securities_tax  = (buy_total + sell_total) * 0.000036396     # 유관기관제비용
    fee             = (buy_total + sell_total) * 0.00015         # 위탁수수료 0.015%

    gross_profit = sell_total - buy_total
    capital_gains_tax = 0.0
    if is_major and gross_profit > 0:
        # 대주주 양도세 22% (지방세 포함, 과세표준 3억 이하 구간 단순화·기본공제 미반영)
        capital_gains_tax = gross_profit * 0.22

    total_cost = transaction_tax + securities_tax + fee + capital_gains_tax
    net_profit = gross_profit - total_cost

    return {
        "buy_total":         round(buy_total),
        "sell_total":        round(sell_total),
        "transaction_tax":   round(transaction_tax),
        "securities_tax":    round(securities_tax),
        "fee":               round(fee),
        "capital_gains_tax": round(capital_gains_tax),
        "total_cost":        round(total_cost),
        "net_profit":        round(net_profit),
        "net_profit_pct":    round(net_profit / buy_total * 100, 2) if buy_total else 0,
    }


@router.get("/api/tax/summary", dependencies=[Depends(api_require_login)])
def tax_summary(request: Request):
    """연도별 세금 요약."""
    year    = request.query_params.get("year")
    user_no = get_user_no(request)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # ── 매도 거래 집계 ──
            if year:
                cur.execute("""
                    SELECT code, name, quantity, price, total,
                           DATE_FORMAT(traded_at, '%%Y-%%m') AS ym
                    FROM stock_transactions
                    WHERE member_id = %s AND type = 'sell'
                      AND YEAR(traded_at) = %s
                    ORDER BY traded_at ASC
                """, (user_no, year))
            else:
                cur.execute("""
                    SELECT code, name, quantity, price, total,
                           DATE_FORMAT(traded_at, '%%Y-%%m') AS ym
                    FROM stock_transactions
                    WHERE member_id = %s AND type = 'sell'
                    ORDER BY traded_at ASC
                """, (user_no,))
            sells = cur.fetchall()

            # ── 매수 기록 (평균단가 계산용) ──
            cur.execute("""
                SELECT code, quantity, price, traded_at
                FROM stock_transactions
                WHERE member_id = %s AND type = 'buy'
                ORDER BY code, traded_at ASC
            """, (user_no,))
            buys = cur.fetchall()
    finally:
        conn.close()

    # 종목별 평균단가 추적 (FIFO 근사: 단순 가중평균)
    avg_map: dict[str, dict] = {}
    for b in buys:
        code = b["code"]
        qty  = int(b["quantity"])
        price = int(b["price"])
        if code not in avg_map:
            avg_map[code] = {"avg": 0, "qty": 0}
        c = avg_map[code]
        new_qty = c["qty"] + qty
        c["avg"] = ((c["avg"] * c["qty"]) + (price * qty)) // new_qty if new_qty else 0
        c["qty"] = new_qty

    # 매도별 세금 계산
    total_sell_amount    = 0
    total_transaction_tax = 0
    total_realized_pnl   = 0
    monthly: dict[str, dict] = {}

    for s in sells:
        code       = s["code"]
        qty        = int(s["quantity"])
        sell_price = int(s["price"])
        sell_total = int(s["total"] or sell_price * qty)
        ym         = s["ym"]

        avg_price     = avg_map.get(code, {}).get("avg", sell_price)
        realized_pnl  = (sell_price - avg_price) * qty
        trans_tax     = round(sell_total * TRANSACTION_TAX_RATE)

        total_sell_amount     += sell_total
        total_transaction_tax += trans_tax
        total_realized_pnl    += realized_pnl

        # 월별 집계
        if ym not in monthly:
            monthly[ym] = {"sell_amount": 0, "transaction_tax": 0, "realized_pnl": 0, "net_profit": 0}
        monthly[ym]["sell_amount"]     += sell_total
        monthly[ym]["transaction_tax"] += trans_tax
        monthly[ym]["realized_pnl"]    += realized_pnl
        monthly[ym]["net_profit"]      += realized_pnl - trans_tax

        # 평균단가 차감 (판매 후 보유량 감소)
        if code in avg_map:
            avg_map[code]["qty"] = max(0, avg_map[code]["qty"] - qty)

    net_profit = total_realized_pnl - total_transaction_tax

    monthly_list = [
        {"ym": k, **v} for k, v in sorted(monthly.items())
    ]

    return {
        "ok": True,
        "year": year or "전체",
        "summary": {
            "total_sell_amount":    total_sell_amount,
            "total_transaction_tax": total_transaction_tax,
            "total_realized_pnl":   total_realized_pnl,
            "net_profit":           net_profit,
            "transaction_tax_rate": f"{TRANSACTION_TAX_RATE * 100:.2f}%",
            "capital_gains_tax":    "비과세 (소액주주 현행법)",
        },
        "monthly": monthly_list,
    }


@router.post("/api/tax/dividend", dependencies=[Depends(api_require_login)])
def calc_dividend_tax(request: Request, data: dict = Body(default={})):
    """배당금 입력 시 세후 금액 계산."""
    dividend_amount = int(data.get("amount", 0))
    if dividend_amount <= 0:
        return JSONResponse({"ok": False, "error": "배당금을 입력해주세요."}, status_code=400)

    tax    = round(dividend_amount * DIVIDEND_TAX_RATE)
    net    = dividend_amount - tax

    return {
        "ok": True,
        "dividend_amount":  dividend_amount,
        "tax":              tax,
        "net_amount":       net,
        "tax_rate":         f"{DIVIDEND_TAX_RATE * 100:.1f}%",
        "breakdown": {
            "income_tax":   round(dividend_amount * 0.14),
            "local_tax":    round(dividend_amount * 0.014),
        },
    }


@router.get("/api/tax/years", dependencies=[Depends(api_require_login)])
def get_available_years(request: Request):
    """거래 기록이 있는 연도 목록."""
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT YEAR(traded_at) AS yr
                FROM stock_transactions
                WHERE member_id = %s AND type = 'sell'
                ORDER BY yr DESC
            """, (user_no,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return {"ok": True, "years": [r["yr"] for r in rows]}
