"""routes/screener.py — 52주 신고가/신저가 스크리너 + 실적 캘린더."""
import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from database.db_connection import get_db_connection

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_52W_CACHE: dict = {'data': None, 'ts': 0.0}
_52W_TTL  = 3600  # 1시간
_52W_LOCK = asyncio.Lock()

_UNIV_CACHE: dict = {'tickers': None, 'ts': 0.0}
_UNIV_TTL  = 86400  # 1일 (시총 순위는 천천히 변함)
_UNIV_TOP_N = 200

# FDR 상장목록 조회 실패 시 폴백용 대형주 (모두 KOSPI)
UNIVERSE_SAMPLE = [
    '005930','000660','373220','207940','005380','068270','000270','005490',
    '006400','051910','035420','035720','012330','028260','105560','055550',
    '086790','066570','015760','247540','086520','003670','096770','017670',
    '030200','323410','259960','036570','034020','012450','010130','090430',
    '018260','352820','267250','032830','047810','316140','011070','032640',
]


def _get_universe() -> list:
    """시총 상위 N개 종목의 yfinance 티커 목록. FDR 상장목록(KOSPI+KOSDAQ) 기반,
    실패 시 하드코딩 대형주로 폴백. 시총 순위는 천천히 바뀌므로 1일 캐시."""
    now = time.time()
    if _UNIV_CACHE['tickers'] and now - _UNIV_CACHE['ts'] < _UNIV_TTL:
        return _UNIV_CACHE['tickers']
    try:
        import FinanceDataReader as fdr
        import pandas as pd
        frames = []
        for mkt, suf in (('KOSPI', '.KS'), ('KOSDAQ', '.KQ')):
            d = fdr.StockListing(mkt)[['Code', 'Marcap']].copy()
            d['suffix'] = suf
            frames.append(d)
        df = pd.concat(frames).dropna(subset=['Marcap'])
        df = df.sort_values('Marcap', ascending=False).head(_UNIV_TOP_N)
        tickers = [f"{str(r.Code).zfill(6)}{r.suffix}" for r in df.itertuples()]
        if tickers:
            _UNIV_CACHE['tickers'] = tickers
            _UNIV_CACHE['ts']      = now
            return tickers
    except Exception as e:
        logger.warning(f'[screener/universe] {e}')
    return [f'{c}.KS' for c in UNIVERSE_SAMPLE]


def _fetch_52w() -> list:
    try:
        import yfinance as yf
        from datetime import datetime, timedelta
        end   = datetime.now()
        start = end - timedelta(days=364)   # 실제 52주
        tickers = _get_universe()
        raw   = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False, threads=True)
        if raw is None or raw.empty:
            return []
        close = raw['Close'] if 'Close' in raw.columns else raw
        result = []
        for t in tickers:
            if t not in close.columns:
                continue
            s = close[t].dropna()
            if len(s) < 20:
                continue
            cur  = float(s.iloc[-1])
            high = float(s.max())
            low  = float(s.min())
            code = t.replace('.KS', '').replace('.KQ', '')
            result.append({
                'code':         code,
                'price':        round(cur, 0),
                'week52_high':  round(high, 0),
                'week52_low':   round(low, 0),
                'pct_from_high': round((cur - high) / high * 100, 2),
                'pct_from_low':  round((cur - low)  / low  * 100, 2),
            })
        return result
    except Exception as e:
        logger.warning(f'[screener/52w] {e}')
        return []


@router.get('/api/screener/52week')
async def screener_52week(filter: str = 'high'):
    now = time.time()
    async with _52W_LOCK:
        if _52W_CACHE['data'] is None or now - _52W_CACHE['ts'] > _52W_TTL:
            data = await asyncio.to_thread(_fetch_52w)
            _52W_CACHE['data'] = data
            _52W_CACHE['ts']   = now
        else:
            data = _52W_CACHE['data']

    if filter == 'high':
        items = sorted([d for d in data if d['pct_from_high'] >= -5],
                       key=lambda x: x['pct_from_high'], reverse=True)
    else:
        items = sorted([d for d in data if d['pct_from_low'] <= 5],
                       key=lambda x: x['pct_from_low'])

    # 종목명 조회
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            codes = [i['code'] for i in items]
            if codes:
                ph = ','.join(['%s'] * len(codes))
                cur.execute(f"SELECT code, name FROM kr_stocks WHERE code IN ({ph})", codes)
                name_map = {r['code']: r['name'] for r in cur.fetchall()}
        conn.close()
        for i in items:
            i['name'] = name_map.get(i['code'], i['code'])
    except Exception:
        for i in items:
            i['name'] = i['code']

    return JSONResponse({'ok': True, 'filter': filter, 'items': items[:30]})


@router.get('/api/screener/earnings-calendar')
def earnings_calendar():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, event_date, event_type, title, importance, country, notified
                FROM event_calendar
                WHERE event_type IN ('earnings','실적','분기보고서','사업보고서')
                ORDER BY event_date ASC LIMIT 50
            """)
            rows = cur.fetchall()
        conn.close()
        for r in rows:
            if hasattr(r.get('event_date'), 'isoformat'):
                r['event_date'] = r['event_date'].isoformat()
        return JSONResponse({'ok': True, 'events': rows})
    except Exception as e:
        logger.error(f'[screener/earnings-calendar] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'events': [], 'error': '서버 오류가 발생했습니다.'})
