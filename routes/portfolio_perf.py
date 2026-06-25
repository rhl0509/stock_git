"""routes/portfolio_perf.py — 포트폴리오 월별 성과."""
import logging
from fastapi import APIRouter, Request, Depends
from routes.utils import require_login, api_require_login, get_user_no
from database.db_connection import get_db_connection
from templates_config import render

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/portfolio_perf', dependencies=[Depends(require_login)])
def portfolio_perf_page(request: Request):
    return render(request, 'stock/portfolio_perf.html')


@router.get('/api/portfolio_perf', dependencies=[Depends(api_require_login)])
def api_portfolio_perf(request: Request):
    user_no = get_user_no(request)
    return {'ok': True, **compute_monthly_perf(user_no)}


def compute_monthly_perf(user_no: int, with_benchmark: bool = True) -> dict:
    """stock_transactions 기반 월별 실현손익(FIFO) + KOSPI 벤치마크 집계.
    라우트와 테스트에서 공용. 반환: {'monthly': [...], 'summary': {...}}"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 월별 실현손익: sell 거래 기준 (total = 매도금액, 매수금액은 avg_price 기준으로 계산 불가 → sell total - buy cost replay)
            cur.execute("""
                SELECT
                    DATE_FORMAT(traded_at, '%%Y-%%m') AS ym,
                    SUM(CASE WHEN type='sell' THEN total ELSE 0 END) AS sell_amt,
                    SUM(CASE WHEN type='buy'  THEN total ELSE 0 END) AS buy_amt,
                    COUNT(CASE WHEN type='sell' THEN 1 END)           AS sell_cnt,
                    COUNT(CASE WHEN type='buy'  THEN 1 END)           AS buy_cnt
                FROM stock_transactions
                WHERE member_id = %s
                GROUP BY ym
                ORDER BY ym ASC
            """, (user_no,))
            monthly = cur.fetchall()

            # 종목별 FIFO 실현손익 계산
            cur.execute("""
                SELECT code, name, type, quantity, price, total,
                       DATE_FORMAT(traded_at, '%%Y-%%m') AS ym,
                       traded_at
                FROM stock_transactions
                WHERE member_id = %s
                ORDER BY code, traded_at ASC
            """, (user_no,))
            all_trades = cur.fetchall()
    finally:
        conn.close()

    # FIFO 실현손익 계산
    from collections import defaultdict, deque
    buy_queue  = defaultdict(deque)   # code → deque of (qty, price)
    realized   = defaultdict(float)   # ym → pnl
    cost_basis = defaultdict(float)   # ym → 해당 월 매도분의 취득원가 (수익률 분모)
    trades_by_ym = defaultdict(list)  # ym → 개별 매도(실현) 상세 리스트

    for t in all_trades:
        code = t['code']
        ym   = t['ym']
        qty  = t['quantity']
        price = t['price']
        if t['type'] == 'buy':
            buy_queue[code].append([qty, price])
        elif t['type'] == 'sell':
            remaining = qty
            cost = 0.0
            while remaining > 0 and buy_queue[code]:
                head_qty, head_price = buy_queue[code][0]
                take = min(remaining, head_qty)
                cost += take * head_price
                remaining -= take
                if take == head_qty:
                    buy_queue[code].popleft()
                else:
                    buy_queue[code][0][0] -= take
            pnl_t = price * qty - cost
            realized[ym]   += pnl_t
            cost_basis[ym] += cost
            ta = t.get('traded_at')
            trades_by_ym[ym].append({
                'code':       code,
                'name':       t.get('name') or code,
                'date':       ta.strftime('%Y-%m-%d') if hasattr(ta, 'strftime') else str(ta)[:10],
                'quantity':   qty,
                'sell_price': price,
                'buy_price':  round(cost / qty) if qty else 0,
                'amount':     int(price * qty),
                'pnl':        round(pnl_t),
                'ret_pct':    round(pnl_t / cost * 100, 2) if cost > 0 else None,
            })

    # KOSPI 월별 수익률 (yfinance)
    kospi_monthly = {}
    try:
        if not with_benchmark:
            raise RuntimeError('benchmark skipped')
        import yfinance as yf
        from datetime import datetime, timedelta
        end   = datetime.now()
        start = end - timedelta(days=730)
        df = yf.Ticker('^KS11').history(start=start, end=end)
        if not df.empty:
            df_m = df['Close'].resample('ME').last()
            df_ret = df_m.pct_change().dropna()
            for dt, ret in df_ret.items():
                kospi_monthly[dt.strftime('%Y-%m')] = round(float(ret) * 100, 2)
    except Exception as e:
        logger.debug(f'[portfolio_perf] kospi 실패: {e}')

    # 월별 집계 — 거래가 있는 달만 (KOSPI 데이터만 있는 달로 빈 행을 만들지 않음)
    months_set = set(t['ym'] for t in all_trades)
    result = []
    for ym in sorted(months_set):
        pnl   = round(realized.get(ym, 0.0))
        basis = cost_basis.get(ym, 0.0)
        m     = next((r for r in monthly if r['ym'] == ym), {})
        result.append({
            'ym':        ym,
            'pnl':       pnl,
            'ret_pct':   round(pnl / basis * 100, 2) if basis > 0 else None,
            'sell_amt':  int(m.get('sell_amt') or 0),
            'buy_amt':   int(m.get('buy_amt') or 0),
            'sell_cnt':  int(m.get('sell_cnt') or 0),
            'buy_cnt':   int(m.get('buy_cnt') or 0),
            'kospi_ret': kospi_monthly.get(ym),
            'trades':    sorted(trades_by_ym.get(ym, []), key=lambda x: x['date'], reverse=True),
        })

    total_pnl   = sum(r['pnl'] for r in result)
    win_months  = sum(1 for r in result if r['pnl'] > 0)
    total_months = len([r for r in result if r['sell_amt'] > 0])

    return {
        'monthly': result,
        'summary': {
            'total_pnl':    total_pnl,
            'win_months':   win_months,
            'total_months': total_months,
            'win_rate':     round(win_months / total_months * 100, 1) if total_months else 0,
        }
    }
