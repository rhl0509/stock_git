"""
routes/paper_trading.py — 가상매매 현황 페이지 + API + 주식 홈 대시보드.
"""
import json
from pathlib import Path
from fastapi import APIRouter, Request, Depends
from routes.utils import require_login_smart
from templates_config import render
from bot.paper_trading import open_new_trades, check_open_trades, get_summary, _load_trades

router = APIRouter(dependencies=[Depends(require_login_smart)])

TRADES_JSON    = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "paper_trades.json"
RECOMMEND_JSON = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "daily_recommend.json"


@router.get("/paper_trading")
def paper_trading_page(request: Request):
    return render(request, "stock/paper_trading.html")


@router.get("/api/paper_trading/summary")
def api_summary():
    return get_summary()


@router.get("/api/paper_trading/trades")
def api_trades(request: Request):
    status = request.query_params.get("status", "")
    trades = _load_trades()
    if status:
        trades = [t for t in trades if t["status"] == status]
    trades.sort(key=lambda t: t.get("entry_date", ""), reverse=True)
    return trades


@router.post("/api/paper_trading/run")
def api_run():
    opened  = open_new_trades()
    result  = check_open_trades()
    summary = get_summary()
    return {"ok": True, "opened": opened, "check": result, "summary": summary}


@router.get("/api/paper_trading/pnl_history")
def api_pnl_history():
    trades = _load_trades()
    closed = [t for t in trades if t.get("status") != "OPEN" and t.get("exit_date") and t.get("net_return_pct") is not None]
    closed.sort(key=lambda t: t["exit_date"])

    cumulative, points = 0.0, []
    for t in closed:
        ret        = t.get("net_return_pct", t.get("return_pct", 0))
        cumulative = round(cumulative + ret, 2)
        points.append({
            "date":       t["exit_date"],
            "name":       t.get("name", t["code"]),
            "category":   t.get("category", ""),
            "status":     t["status"],
            "net_return": ret,
            "cumulative": cumulative,
        })

    return points


# ─────────────────────────────────────────────────────────────────
# 수동 모의매매 계좌 (React PaperTrading.jsx 계약) — 사용자별 DB 저장
# ─────────────────────────────────────────────────────────────────
import logging
from fastapi import Body
from fastapi.responses import JSONResponse
from database.db_connection import get_db_connection
from routes.utils import get_user_no

logger = logging.getLogger(__name__)
_INITIAL_CASH = 10_000_000  # 초기 가상 예수금 1천만원


def _ensure_paper_tables():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_account (
                    user_no INT PRIMARY KEY,
                    cash    BIGINT NOT NULL
                ) CHARACTER SET utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_positions (
                    id        INT AUTO_INCREMENT PRIMARY KEY,
                    user_no   INT NOT NULL,
                    code      CHAR(6) NOT NULL,
                    name      VARCHAR(100),
                    quantity  INT NOT NULL,
                    avg_price INT NOT NULL,
                    UNIQUE KEY uq_user_code (user_no, code)
                ) CHARACTER SET utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS paper_log (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_no    INT NOT NULL,
                    action     VARCHAR(4) NOT NULL,
                    code       CHAR(6) NOT NULL,
                    name       VARCHAR(100),
                    price      INT NOT NULL,
                    quantity   INT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user (user_no)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()

try:
    _ensure_paper_tables()
except Exception:
    pass


def _get_cash(cur, user_no: int) -> int:
    cur.execute("SELECT cash FROM paper_account WHERE user_no=%s", (user_no,))
    row = cur.fetchone()
    if row:
        return int(row['cash'])
    cur.execute("INSERT INTO paper_account (user_no, cash) VALUES (%s, %s)",
                (user_no, _INITIAL_CASH))
    return _INITIAL_CASH


@router.get("/api/paper_trading/portfolio")
def api_portfolio(request: Request):
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cash = _get_cash(cur, user_no)
            cur.execute("SELECT * FROM paper_positions WHERE user_no=%s ORDER BY id", (user_no,))
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    positions, total_eval, total_profit = [], 0, 0
    for p in rows:
        try:
            from routes.kiwoom import _fetch_naver_price
            cur_price = _fetch_naver_price(p['code']) or p['avg_price']
        except Exception:
            cur_price = p['avg_price']
        eval_amt = cur_price * p['quantity']
        profit   = eval_amt - p['avg_price'] * p['quantity']
        total_eval += eval_amt
        total_profit += profit
        positions.append({
            'id': p['id'], 'code': p['code'], 'name': p['name'],
            'quantity': p['quantity'], 'avg_price': p['avg_price'],
            'current_price': cur_price, 'eval_amount': eval_amt, 'profit': profit,
        })
    return {'account': {'cash': cash, 'total_eval': total_eval, 'total_profit': total_profit},
            'positions': positions}


def _paper_trade(user_no: int, action: str, body: dict):
    code = (body.get('code') or '').strip().zfill(6)[:6]
    name = (body.get('name') or code).strip()
    try:
        price = int(float(body.get('price') or 0))
        qty   = int(body.get('quantity') or 0)
    except (ValueError, TypeError):
        return JSONResponse({'error': '가격/수량을 확인하세요.'}, status_code=400)
    if not code.isdigit() or price <= 0 or qty <= 0:
        return JSONResponse({'error': '종목코드/가격/수량을 확인하세요.'}, status_code=400)

    total = price * qty
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cash = _get_cash(cur, user_no)
            cur.execute("SELECT * FROM paper_positions WHERE user_no=%s AND code=%s",
                        (user_no, code))
            pos = cur.fetchone()

            if action == 'buy':
                if total > cash:
                    return JSONResponse({'error': f'예수금 부족 (보유 ₩{cash:,})'}, status_code=400)
                if pos:
                    new_qty = pos['quantity'] + qty
                    new_avg = round((pos['avg_price'] * pos['quantity'] + total) / new_qty)
                    cur.execute("UPDATE paper_positions SET quantity=%s, avg_price=%s, name=%s WHERE id=%s",
                                (new_qty, new_avg, name, pos['id']))
                else:
                    cur.execute("INSERT INTO paper_positions (user_no, code, name, quantity, avg_price) "
                                "VALUES (%s,%s,%s,%s,%s)", (user_no, code, name, qty, price))
                cur.execute("UPDATE paper_account SET cash = cash - %s WHERE user_no=%s",
                            (total, user_no))
            else:  # sell
                if not pos or pos['quantity'] < qty:
                    held = pos['quantity'] if pos else 0
                    return JSONResponse({'error': f'보유 수량 부족 (보유 {held}주)'}, status_code=400)
                if pos['quantity'] == qty:
                    cur.execute("DELETE FROM paper_positions WHERE id=%s", (pos['id'],))
                else:
                    cur.execute("UPDATE paper_positions SET quantity = quantity - %s WHERE id=%s",
                                (qty, pos['id']))
                cur.execute("UPDATE paper_account SET cash = cash + %s WHERE user_no=%s",
                            (total, user_no))

            cur.execute("INSERT INTO paper_log (user_no, action, code, name, price, quantity) "
                        "VALUES (%s,%s,%s,%s,%s,%s)", (user_no, action, code, name, price, qty))
        conn.commit()
        return {'ok': True}
    except Exception as e:
        conn.rollback()
        logger.error(f'[paper_trading/{action}] {e}', exc_info=True)
        return JSONResponse({'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post("/api/paper_trading/buy")
def api_buy(request: Request, body: dict = Body(default={})):
    return _paper_trade(get_user_no(request), 'buy', body)


@router.post("/api/paper_trading/sell")
def api_sell(request: Request, body: dict = Body(default={})):
    return _paper_trade(get_user_no(request), 'sell', body)


@router.post("/api/paper_trading/reset")
def api_reset(request: Request):
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM paper_positions WHERE user_no=%s", (user_no,))
            cur.execute("DELETE FROM paper_log WHERE user_no=%s", (user_no,))
            cur.execute("REPLACE INTO paper_account (user_no, cash) VALUES (%s, %s)",
                        (user_no, _INITIAL_CASH))
        conn.commit()
        return {'ok': True, 'cash': _INITIAL_CASH}
    finally:
        conn.close()


@router.get("/api/paper_trading/log")
def api_log(request: Request):
    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action, code, name, price, quantity, "
                "DATE_FORMAT(created_at,'%%Y-%%m-%%d %%H:%%i') AS created_at "
                "FROM paper_log WHERE user_no=%s ORDER BY id DESC LIMIT 100",
                (user_no,))
            logs = cur.fetchall()
    finally:
        conn.close()
    return {'logs': logs}


# NOTE: /stock_dashboard 페이지 라우트는 app.py에 정의 (여기 중복 정의 시 인증이 우회됨)
@router.get("/api/stock_dashboard")
def api_stock_dashboard():
    summary = get_summary()

    recommend = {}
    if RECOMMEND_JSON.exists():
        try:
            data = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
            recommend = {
                "generated_at": data.get("generated_at", ""),
                "base_date":    data.get("base_date", ""),
                "n_buy":        data.get("n_buy", 0),
                "model_used":   data.get("model_used", False),
                "n_triple":     len(data.get("triple", [])),
                "n_daily":      len(data.get("daily", [])),
                "n_short":      len(data.get("short", [])),
                "n_swing":      len(data.get("swing", [])),
            }
        except Exception:
            pass

    model_dir   = RECOMMEND_JSON.parent
    model_files = ["xgb_v2_daily.json", "xgb_v2_short.json", "xgb_v2_swing.json"]
    model_status = {f.replace("xgb_v2_", "").replace(".json", ""): (model_dir / f).exists()
                    for f in model_files}

    return {"paper": summary, "recommend": recommend, "model": model_status}
