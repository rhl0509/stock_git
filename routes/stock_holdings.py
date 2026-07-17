import logging
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from database.db_connection import get_db_connection
from routes.utils import api_require_login, get_user_no, require_owner, is_owner_user_no
from kiwoom_client import kiwoom
from datetime import datetime as _dt, timedelta as _timedelta
import time as _time

router = APIRouter()
logger = logging.getLogger(__name__)


def _enqueue_trade(cursor, user_no: int, txn_id: int, name: str, kind: str,
                   quantity: int, total: int, profit: int | None = None) -> None:
    """매매 1건을 가계부 아웃박스에 적재한다(호출자의 트랜잭션 안에서).

    2026-07-17 이전에는 여기서 자기 DB 의 transactions 에 직접 INSERT 했다. 가계부가
    별도 DB(gagebu)로 분리되면서 그 테이블은 아무도 읽지 않는 고아가 됐고, 게다가
    `SELECT id FROM account_books WHERE member_id=%s` 가 없으면 400 으로 **매수 자체를
    막고 있었다** — 실측 결과 회원 10명 중 8명이 그 행이 없어 매수가 불가능했다.
    고아 테이블 조회가 본 기능을 막던 것이므로 게이트를 걷어냈다.

    Args:
        txn_id: 방금 넣은 stock_transactions 행의 id. **호출자가 명시적으로 넘긴다** —
            여기서 cursor.lastrowid 를 읽으면 "직전 statement 가 그 INSERT" 라는
            암묵 전제에 매달리게 되고, 사이에 한 줄만 끼어들면 키가 trade|0 으로
            고정돼 두 번째 이후 매매가 중복키로 전부 사라진다.
    """
    from gagebu_outbox import enqueue, make_key
    from routes.utils import get_owner_user_no

    # 현금흐름 기준: 매수는 돈이 나가고(expense) 매도는 총액이 들어온다(income).
    # 둘을 합치면 순증분이 곧 손익이 된다.
    # 카테고리 힌트는 가계부의 화이트리스트(_MANAGED_CATEGORIES)에 있는 이름만
    # 만들어진다 — 임의 이름을 보내도 미분류로 떨어질 뿐 장부가 늘지 않는다.
    if kind == 'buy':
        type_val, title, hint = 'expense', f"{name} 매수 {quantity}주", '매수'
    else:
        type_val = 'income'
        title = f"{name} 매도 {quantity}주 (수익: {profit:+,}원)"
        hint = '매도'

    # 키에 member_id 를 넣는다 — 아웃박스는 UNIQUE(idempotency_key) 전역이고 가계부
    # 원장은 UNIQUE(account_book_id, idempotency_key) 스코프별이라 비대칭이다. 지금은
    # trade|{id} 가 전역 PK 라 안전하지만, 회원별 배당 잡이 생기면 같은 종목·같은
    # 배당락일을 보유한 두 회원이 같은 키를 만들어 한쪽이 조용히 사라진다.
    enqueue(cursor,
            idempotency_key=make_key('trade', user_no, txn_id),
            source='trade', member_id=user_no, type_val=type_val,
            amount=total, title=title,
            date_str=_dt.now().strftime('%Y-%m-%d'),
            category_hint=hint,
            owner_user_no=get_owner_user_no())


# 키움 계좌 동기화 시 가져올 실현손익 기간(일). 과거 월까지 보이도록 1년치 조회.
SYNC_TRADE_DAYS = 365
# opt10073(일자별실현손익)은 조회기간이 약 3개월을 넘으면 0행을 반환한다.
# 따라서 기간을 80일 단위 청크로 끊어 호출한 뒤 합친다.
_REALIZED_CHUNK_DAYS = 80


@router.get('/stock/holdings', dependencies=[Depends(api_require_login)])
def get_holdings(request: Request):
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM stock_holdings WHERE member_id = %s",
                (user_no,)
            )
            holdings = cursor.fetchall()

        result       = []
        total_asset  = 0
        total_invest = 0

        for h in holdings:
            price_data    = kiwoom.get_best_price(h['code'])
            current_price = price_data['price']        if price_data else h['avg_price']
            price_source  = price_data['price_source'] if price_data else 'UNKNOWN'

            invest      = h['avg_price'] * h['quantity']
            eval_amount = current_price  * h['quantity']
            profit      = eval_amount - invest
            profit_rate = round((profit / invest) * 100, 2) if invest else 0

            total_asset  += eval_amount
            total_invest += invest

            result.append({
                "id":            h['id'],
                "code":          h['code'],
                "name":          h['name'],
                "quantity":      h['quantity'],
                "avg_price":     h['avg_price'],
                "current_price": current_price,
                "price_source":  price_source,
                "invest":        invest,
                "eval_amount":   eval_amount,
                "profit":        profit,
                "profit_rate":   profit_rate,
            })

        total_profit      = total_asset - total_invest
        total_profit_rate = round((total_profit / total_invest) * 100, 2) if total_invest else 0

        return {
            "holdings": result,
            "summary": {
                "total_invest":      total_invest,
                "total_asset":       total_asset,
                "total_profit":      total_profit,
                "total_profit_rate": total_profit_rate,
            }
        }
    finally:
        conn.close()


@router.post('/stock/holdings', dependencies=[Depends(api_require_login)])
def add_holding(request: Request, data: dict = Body(default={})):
    """보유종목 수동 추가/갱신 (React StockPortfolioKr.jsx 계약)."""
    user_no   = get_user_no(request)
    code      = (data.get('code') or '').strip().zfill(6)[:6]
    quantity  = _to_int(data.get('quantity'))
    avg_price = _to_int(data.get('avg_price'))
    if not code.isdigit() or quantity <= 0 or avg_price <= 0:
        return JSONResponse({"error": "종목코드/수량/평균단가를 확인하세요."}, status_code=400)

    name = (data.get('name') or '').strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if not name or name == code:
                cursor.execute("SELECT name FROM kr_stocks WHERE code=%s", (code,))
                row = cursor.fetchone()
                name = row['name'] if row else code
            cursor.execute(
                "SELECT id FROM stock_holdings WHERE member_id=%s AND code=%s",
                (user_no, code))
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE stock_holdings SET name=%s, quantity=%s, avg_price=%s WHERE id=%s",
                    (name, quantity, avg_price, existing['id']))
            else:
                cursor.execute(
                    "INSERT INTO stock_holdings (member_id, code, name, quantity, avg_price) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (user_no, code, name, quantity, avg_price))
        conn.commit()
        return {"ok": True, "name": name}
    except Exception as e:
        conn.rollback()
        logger.error(f'[stock_holdings/add] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.delete('/stock/holdings/{holding_id}', dependencies=[Depends(api_require_login)])
def delete_holding(holding_id: int, request: Request):
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM stock_holdings WHERE id = %s AND member_id = %s",
                (holding_id, user_no)
            )
            if cursor.rowcount == 0:
                return JSONResponse({"error": "종목을 찾을 수 없습니다."}, status_code=404)
        conn.commit()
        return {"status": "ok", "message": "종목이 삭제되었습니다."}
    except Exception as e:
        conn.rollback()
        logger.error(f'[stock_holdings] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


def _to_int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    try:
        return int(str(v).replace(',', '').replace(' ', '') or 0)
    except (ValueError, TypeError):
        return 0


def _build_tx_from_realized(realized, today_yyyymmdd: str):
    """키움 실현손익(opt10073) 행 → 트랜잭션 튜플 리스트.
    실현(매도) 1건당 같은 수량의 매수+매도를 합성해, 월별성과 FIFO 실현손익이
    키움 손익과 일치하도록 한다. 데이터 없으면 None(→상위에서 opw00015 폴백)."""
    if not isinstance(realized, dict):
        return None
    rows = realized.get('stocks')
    if not rows:
        return None
    # opt10073은 매도(실현)뿐 아니라 매수 행도 반환한다. 매수/손익0 행은
    # 실현손익 집계 대상이 아니므로 제외 — 매도로 오인해 가짜손익이 생기지 않도록.
    valid = []
    for r in rows:
        code = (r.get('code') or '').strip()
        qty  = _to_int(r.get('quantity'))
        sp   = _to_int(r.get('sell_price'))
        pnl  = _to_int(r.get('pnl'))
        if not code or qty <= 0 or sp <= 0 or pnl == 0:
            continue
        rdate = str(r.get('date') or today_yyyymmdd).strip().zfill(8)
        valid.append((rdate, code, (r.get('name') or code).strip(), qty, sp, pnl))
    if not valid:
        return None

    # 합성 매수+매도 쌍이 FIFO에서 다른 행과 교차 매칭되지 않도록 쌍마다 고유 시각 부여
    # (매수 직후 같은 수량 매도). → 월별성과 실현손익이 키움 손익과 정확히 일치.
    valid.sort(key=lambda x: x[0])
    out, per_date = [], {}
    for rdate, code, name, qty, sp, pnl in valid:
        # 실현손익으로 매입단가 역산: (매도가-매입가)*수량 = 실현손익
        bp = sp - round(pnl / qty)
        if bp < 0:
            bp = 0
        d = f"{rdate[:4]}-{rdate[4:6]}-{rdate[6:8]}"
        k = per_date.get(rdate, 0)
        per_date[rdate] = k + 1
        base = _dt.strptime(f"{d} 09:00:00", "%Y-%m-%d %H:%M:%S")
        bt = (base + _timedelta(seconds=2 * k)).strftime("%Y-%m-%d %H:%M:%S")
        st = (base + _timedelta(seconds=2 * k + 1)).strftime("%Y-%m-%d %H:%M:%S")
        out.append((code, name, 'buy',  qty, bp, bp * qty, bt))
        out.append((code, name, 'sell', qty, sp, sp * qty, st))
    return out or None


def _build_tx_from_period(period_trades, today_yyyymmdd: str):
    """키움 기간체결(opw00015) 행 → 트랜잭션 튜플 리스트. None이면 조회 실패."""
    if period_trades is None:
        return None
    out = []
    for t in period_trades:
        code  = (t.get('code') or '').strip()
        name  = (t.get('name') or code).strip()
        qty   = _to_int(t.get('quantity'))
        price = _to_int(t.get('price'))
        total = _to_int(t.get('total')) or price * qty
        ttype = t.get('type', 'buy')
        rdate = str(t.get('date', today_yyyymmdd)).zfill(8)
        ttime = str(t.get('time', '000000')).zfill(6)
        if not code or qty <= 0 or price <= 0:
            continue
        d  = f"{rdate[:4]}-{rdate[4:6]}-{rdate[6:8]}"
        ts = f"{d} {ttime[:2]}:{ttime[2:4]}:{ttime[4:6]}"
        out.append((code, name, ttype, qty, price, total, ts))
    return out


def _fetch_realized_chunked(now_dt) -> dict:
    """opt10073(실현손익)을 80일 청크로 나눠 조회·병합.
    opt10073은 조회기간이 약 3개월을 넘으면 0행을 반환하므로 청크가 필요.
    어떤 청크도 응답하지 못하면 None(→상위에서 opw00015 폴백)."""
    start = now_dt - _timedelta(days=SYNC_TRADE_DAYS)
    merged, got_any = {}, False
    cur = start
    while cur <= now_dt:
        c_to = min(cur + _timedelta(days=_REALIZED_CHUNK_DAYS - 1), now_dt)
        r = kiwoom.get_realized_pnl(cur.strftime('%Y%m%d'), c_to.strftime('%Y%m%d'))
        if isinstance(r, dict):
            got_any = True
            for s in r.get('stocks') or []:
                key = (s.get('code'), s.get('date'), _to_int(s.get('quantity')),
                       _to_int(s.get('sell_price')), _to_int(s.get('pnl')))
                merged[key] = s
        cur = c_to + _timedelta(days=1)
        _time.sleep(0.25)   # 키움 TR 조회 제한 회피
    if not got_any:
        return None
    return {'stocks': list(merged.values())}


def do_kiwoom_sync(user_no: int) -> dict:
    """키움 계좌 → DB 동기화 핵심 로직. 라우트와 자동화 잡(auto_jobs)에서 공용.
    반환: {"ok": bool, "error"?: str, "count"?, "trade_synced"?, "deposit"?}"""
    # 키움 콜렉터는 주인 단일계좌에 묶여 있다. 비소유자 user_no 로 동기화하면 주인 계좌가
    # 그 회원 행에 덮어써져(사생활 유출+데이터 오염) 위험하므로 소유자만 허용.
    if not is_owner_user_no(user_no):
        return {"ok": False, "error": "키움 계좌 동기화는 계정 소유자만 가능합니다."}
    if kiwoom.get_login_state() != 1:
        return {"ok": False, "error": "키움 API에 로그인되어 있지 않습니다."}

    full = kiwoom.get_account_full()
    if full is None:
        return {"ok": False, "error": "키움 계좌 보유종목 조회에 실패했습니다."}

    holdings       = full.get('holdings') or []
    deposit        = _to_int(full.get('deposit'))
    now_dt         = _dt.now()
    today_yyyymmdd = now_dt.strftime('%Y%m%d')
    from_dt        = now_dt - _timedelta(days=SYNC_TRADE_DAYS)
    from_yyyymmdd  = from_dt.strftime('%Y%m%d')

    # 거래 원천: 실현손익(opt10073) 우선 — opw00015(기간체결)는 계좌에 따라 0행을
    # 반환해 신뢰도가 낮다. 실현손익이 비면 기간체결로 폴백.
    tx_rows = _build_tx_from_realized(
        _fetch_realized_chunked(now_dt), today_yyyymmdd)
    if not tx_rows:
        tx_rows = _build_tx_from_period(
            kiwoom.get_period_trades(from_yyyymmdd, today_yyyymmdd), today_yyyymmdd)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM stock_holdings WHERE member_id = %s", (user_no,))
            synced = 0
            for h in holdings:
                qty       = _to_int(h.get('quantity'))
                avg_price = _to_int(h.get('avg_price'))
                code      = (h.get('code') or '').strip()
                name      = (h.get('name') or code).strip()
                if qty > 0 and code:
                    cursor.execute(
                        "INSERT INTO stock_holdings (member_id, code, name, quantity, avg_price) VALUES (%s, %s, %s, %s, %s)",
                        (user_no, code, name, qty, avg_price)
                    )
                    synced += 1

            trade_synced = 0
            if tx_rows is not None:
                # 키움을 source of truth로 거래내역 전체 교체.
                # (윈도우 밖의 잔여 매수 등이 FIFO 실현손익을 오염시키지 않도록)
                cursor.execute(
                    "DELETE FROM stock_transactions WHERE member_id = %s",
                    (user_no,)
                )
                for (code, name, ttype, qty, price, total, traded_at) in tx_rows:
                    cursor.execute(
                        "INSERT INTO stock_transactions (member_id, code, name, type, quantity, price, total, traded_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_no, code, name, ttype, qty, price, total, traded_at)
                    )
                    if ttype == 'sell':
                        trade_synced += 1

        conn.commit()
        return {"ok": True, "count": synced, "trade_synced": trade_synced, "deposit": deposit}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post('/stock/sync', dependencies=[Depends(require_owner)])
def sync_from_kiwoom(request: Request):
    user_no = get_user_no(request)
    try:
        result = do_kiwoom_sync(user_no)
    except Exception as e:
        logger.error(f'[stock_holdings] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
    if not result.get('ok'):
        status = 400 if '로그인' in result.get('error', '') else 500
        return JSONResponse({"error": result.get('error')}, status_code=status)
    return {
        "status":       "ok",
        "message":      f"키움 동기화 완료 — 보유 {result['count']}종목, 최근 {SYNC_TRADE_DAYS}일 매도 {result['trade_synced']}건",
        "count":        result['count'],
        "trade_synced": result['trade_synced'],
        "deposit":      result['deposit'],
    }


@router.post('/stock/buy', dependencies=[Depends(api_require_login)])
def buy_stock(request: Request, data: dict = Body(default={})):
    user_no = get_user_no(request)
    code = data.get('code', '').strip()
    name = data.get('name', code).strip()

    try:
        quantity = int(data.get('quantity'))
        price    = int(data.get('price'))
    except (TypeError, ValueError):
        return JSONResponse({"error": "수량과 단가는 숫자여야 합니다."}, status_code=400)

    if not code:              return JSONResponse({"error": "종목코드를 입력해주세요."}, status_code=400)
    if quantity <= 0:         return JSONResponse({"error": "수량은 1 이상이어야 합니다."}, status_code=400)
    if price    <= 0:         return JSONResponse({"error": "단가는 1 이상이어야 합니다."}, status_code=400)
    if quantity > 1_000_000:  return JSONResponse({"error": "수량이 너무 큽니다."}, status_code=400)
    if price    > 10_000_000: return JSONResponse({"error": "단가가 너무 큽니다."}, status_code=400)

    total = price * quantity

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # (member_id, code) 유니크 인덱스 기반 원자적 upsert.
            # 동시 첫매수 중복 INSERT · 동시 매수 lost update를 DB 레벨에서 한 번에 방어
            # (행잠금 SELECT 불필요). ON DUPLICATE KEY UPDATE는 좌→우로 평가되므로,
            # 옛 quantity를 쓰는 avg_price를 quantity 재대입보다 반드시 먼저 둔다.
            cursor.execute(
                """INSERT INTO stock_holdings (member_id, code, name, quantity, avg_price)
                   VALUES (%s, %s, %s, %s, %s) AS new
                   ON DUPLICATE KEY UPDATE
                       avg_price = ((stock_holdings.avg_price * stock_holdings.quantity)
                                    + (new.avg_price * new.quantity))
                                   DIV (stock_holdings.quantity + new.quantity),
                       quantity  = stock_holdings.quantity + new.quantity,
                       name      = new.name""",
                (user_no, code, name, quantity, price)
            )

            cursor.execute(
                "INSERT INTO stock_transactions (member_id, code, name, type, quantity, price, total) VALUES (%s, %s, %s, 'buy', %s, %s, %s)",
                (user_no, code, name, quantity, price, total)
            )
            stock_txn_id = cursor.lastrowid
            # 가계부 기록은 이제 별도 앱(gagebu)의 HTTP 다. 이 트랜잭션 안에서 호출하면
            # 가계부 장애가 매수를 실패시키고 HTTP 는 롤백되지도 않는다. 같은 커밋으로
            # 의도만 적재하고 전송은 디스패처가 맡는다(gagebu_outbox 참고).
            _enqueue_trade(cursor, user_no, stock_txn_id, name, 'buy', quantity, total)

        conn.commit()
        return {"status": "ok", "message": f"{name} {quantity}주 매수 완료"}
    except Exception as e:
        conn.rollback()
        logger.error(f'[stock_holdings] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post('/stock/sell', dependencies=[Depends(api_require_login)])
def sell_stock(request: Request, data: dict = Body(default={})):
    user_no = get_user_no(request)
    code = data.get('code', '').strip()
    name = data.get('name', code).strip()

    try:
        quantity = int(data.get('quantity'))
        price    = int(data.get('price'))
    except (TypeError, ValueError):
        return JSONResponse({"error": "수량과 단가는 숫자여야 합니다."}, status_code=400)

    if not code:      return JSONResponse({"error": "종목코드를 입력해주세요."}, status_code=400)
    if quantity <= 0: return JSONResponse({"error": "수량은 1 이상이어야 합니다."}, status_code=400)
    if price    <= 0: return JSONResponse({"error": "단가는 1 이상이어야 합니다."}, status_code=400)

    total = price * quantity

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM stock_holdings WHERE member_id = %s AND code = %s FOR UPDATE",
                (user_no, code)
            )
            existing = cursor.fetchone()

            if not existing:
                return JSONResponse({"error": "보유하지 않은 종목입니다."}, status_code=400)
            if existing['quantity'] < quantity:
                return JSONResponse({"error": f"보유 수량 부족 (보유: {existing['quantity']}주)"}, status_code=400)

            profit  = (price - existing['avg_price']) * quantity
            new_qty = existing['quantity'] - quantity

            if new_qty == 0:
                cursor.execute("DELETE FROM stock_holdings WHERE id = %s", (existing['id'],))
            else:
                cursor.execute(
                    "UPDATE stock_holdings SET quantity = %s WHERE id = %s",
                    (new_qty, existing['id'])
                )

            cursor.execute(
                "INSERT INTO stock_transactions (member_id, code, name, type, quantity, price, total) VALUES (%s, %s, %s, 'sell', %s, %s, %s)",
                (user_no, code, name, quantity, price, total)
            )
            stock_txn_id = cursor.lastrowid
            _enqueue_trade(cursor, user_no, stock_txn_id, name, 'sell', quantity, total,
                           profit=profit)

        conn.commit()
        return {"status": "ok", "message": f"{name} {quantity}주 매도 완료", "profit": profit}
    except Exception as e:
        conn.rollback()
        logger.error(f'[stock_holdings] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.get('/stock/transactions', dependencies=[Depends(api_require_login)])
def get_transactions(request: Request):
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM stock_transactions WHERE member_id = %s ORDER BY traded_at DESC LIMIT 50",
                (user_no,)
            )
            rows = cursor.fetchall()
            for row in rows:
                row['traded_at'] = str(row['traded_at'])
        return rows
    finally:
        conn.close()


@router.get('/stock/daily-trades', dependencies=[Depends(api_require_login)])
def get_daily_trades(request: Request):
    user_no = get_user_no(request)
    date_str = request.query_params.get('date')

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if date_str:
                cursor.execute(
                    "SELECT * FROM stock_transactions WHERE member_id = %s AND DATE(traded_at) = %s ORDER BY traded_at DESC",
                    (user_no, date_str)
                )
            else:
                cursor.execute(
                    "SELECT * FROM stock_transactions WHERE member_id = %s AND DATE(traded_at) = CURDATE() ORDER BY traded_at DESC",
                    (user_no,)
                )
            rows = cursor.fetchall()
            for row in rows:
                row['traded_at'] = str(row['traded_at'])
        return rows
    finally:
        conn.close()


@router.get('/stock/realized-pnl', dependencies=[Depends(api_require_login)])
def get_realized_pnl(request: Request):
    user_no = get_user_no(request)
    from datetime import timedelta
    today     = _dt.now().strftime('%Y-%m-%d')
    today_kw  = _dt.now().strftime('%Y%m%d')
    since_kw  = (_dt.now() - timedelta(days=90)).strftime('%Y%m%d')

    # 키움 실현손익은 주인 단일계좌 데이터다. 소유자만 키움 분기를 타고,
    # 그 외 회원은 자신의 거래내역(stock_transactions) 기반 DB 계산으로 폴백.
    if is_owner_user_no(user_no) and kiwoom.get_login_state() == 1:
        full = kiwoom.get_realized_pnl(since_kw, today_kw)
        if full is not None:
            try:
                today_data = kiwoom.get_realized_pnl(today_kw, today_kw)
                today_pnl  = (today_data or {}).get('total_pnl', 0)
            except Exception:
                today_pnl  = 0
            return {
                'total_realized': full.get('total_pnl', 0),
                'today_realized': today_pnl,
                'source': 'kiwoom',
            }

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT code, type, quantity, price, traded_at FROM stock_transactions "
                "WHERE member_id = %s ORDER BY code, traded_at ASC",
                (user_no,)
            )
            rows = cursor.fetchall()

        avg_map = {}
        total_realized = 0
        today_realized = 0

        for row in rows:
            code  = row['code']
            qty   = int(row['quantity'])
            price = int(row['price'])
            date  = str(row['traded_at'])[:10]
            if code not in avg_map:
                avg_map[code] = {'avg': 0, 'qty': 0}
            if row['type'] == 'buy':
                c = avg_map[code]
                new_qty = c['qty'] + qty
                c['avg'] = ((c['avg'] * c['qty']) + (price * qty)) // new_qty
                c['qty'] = new_qty
            elif row['type'] == 'sell':
                avg    = avg_map[code]['avg'] if avg_map[code]['qty'] > 0 else price
                profit = (price - avg) * qty
                total_realized += profit
                if date == today:
                    today_realized += profit
                avg_map[code]['qty'] = max(0, avg_map[code]['qty'] - qty)

        return {
            'total_realized': total_realized,
            'today_realized': today_realized,
            'source': 'db',
        }
    finally:
        conn.close()
