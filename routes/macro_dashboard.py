"""routes/macro_dashboard.py — 거시지표 대시보드."""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from routes.utils import require_login, api_require_login
from templates_config import render

router = APIRouter()
logger = logging.getLogger(__name__)

# 5분 TTL 캐시 — 매 요청마다 yfinance 10번 호출 방지
_MACRO_CACHE: dict = {'data': None, 'ts': 0.0}
_MACRO_TTL  = 300   # 5분
_MACRO_LOCK = asyncio.Lock()


# ─────────────────────────────────────────────────────────────────
# 동기 헬퍼 (asyncio.to_thread 에서 실행)
# ─────────────────────────────────────────────────────────────────

def _yfinance_series(ticker: str, days: int = 120) -> list:
    try:
        import yfinance as yf
        end   = datetime.now()
        start = end - timedelta(days=days)
        s = yf.Ticker(ticker).history(start=start, end=end)['Close'].dropna()
        return s.tolist()
    except Exception as e:
        logger.debug(f'[macro] yfinance {ticker} 실패: {e}')
        return []


def _last(arr) -> float | None:
    return round(arr[-1], 2) if arr else None


def _pct1d(arr) -> float | None:
    if arr and len(arr) >= 2 and arr[-2]:
        return round((arr[-1] - arr[-2]) / arr[-2] * 100, 2)
    return None


def _build_macro_data() -> dict:
    """모든 거시지표를 한 번에 수집 (blocking — 스레드풀에서 실행)."""
    try:
        from XGBoost_v2.global_features import get_global_features
        g = get_global_features()
    except Exception as e:
        logger.warning(f'[macro] global_features 실패: {e}')
        g = {}

    try:
        from XGBoost_v2.bok_client import get_macro_features, _fetch_indicator, INDICATORS
        m            = get_macro_features()
        kospi_series  = _fetch_indicator(*INDICATORS['kospi'],   n=60)
        usdkrw_series = _fetch_indicator(*INDICATORS['usdkrw'],  n=60)
        bond_series   = _fetch_indicator(*INDICATORS['bond_3y'], n=60)
    except Exception as e:
        logger.warning(f'[macro] bok_client 실패: {e}')
        m = {}
        kospi_series = usdkrw_series = bond_series = []

    # yfinance fallback
    if not kospi_series:
        kospi_series = _yfinance_series('^KS11')
    if kospi_series and len(kospi_series) >= 2:
        m['kospi_price']  = round(kospi_series[-1], 2)
        m['kospi_ret_1d'] = _pct1d(kospi_series)
    if kospi_series and len(kospi_series) >= 20:
        m['kospi_ret_20d'] = round(
            (kospi_series[-1] - kospi_series[-20]) / kospi_series[-20], 4)
        ma20 = sum(kospi_series[-20:]) / 20
        m['kospi_trend'] = round((kospi_series[-1] - ma20) / ma20, 4)

    if not usdkrw_series:
        usdkrw_series = _yfinance_series('USDKRW=X')
    if usdkrw_series and len(usdkrw_series) >= 2:
        m['usdkrw_ret_1d'] = _pct1d(usdkrw_series)
    if usdkrw_series and len(usdkrw_series) >= 20:
        m['usdkrw_ret_20d'] = round(
            (usdkrw_series[-1] - usdkrw_series[-20]) / usdkrw_series[-20], 4)

    if bond_series and len(bond_series) >= 2:
        m['bond_3y_ret_1d'] = _pct1d(bond_series)

    # KOSDAQ
    kosdaq_series = _yfinance_series('^KQ11')
    if kosdaq_series and len(kosdaq_series) >= 2:
        m['kosdaq_price']  = round(kosdaq_series[-1], 2)
        m['kosdaq_ret_1d'] = _pct1d(kosdaq_series)

    # 글로벌 지표
    vix_series   = _yfinance_series('^VIX',  days=60)
    sp500_series = _yfinance_series('^GSPC', days=60)
    nq_series    = _yfinance_series('^IXIC', days=60)
    oil_series   = _yfinance_series('CL=F',  days=60)
    us10y_series = _yfinance_series('^TNX',  days=60)

    if sp500_series:
        g['sp500_price']  = _last(sp500_series)
        if not g.get('sp500_ret_1d'):
            g['sp500_ret_1d'] = _pct1d(sp500_series)
    if nq_series:
        g['nasdaq_price'] = _last(nq_series)
        if not g.get('nasdaq_ret_1d'):
            g['nasdaq_ret_1d'] = _pct1d(nq_series)
    if oil_series:
        g['oil_price']    = _last(oil_series)
    if vix_series:
        if not g.get('vix_level'):
            g['vix_level'] = _last(vix_series)
        g['vix_ret_1d']   = _pct1d(vix_series)
    if us10y_series:
        if not g.get('us_10y'):
            g['us_10y'] = _last(us10y_series)
        g['us_10y_ret_1d'] = _pct1d(us10y_series)

    return {
        'ok': True,
        'global': g,
        'macro':  m,
        'series': {
            'kospi':   kospi_series[-30:]  if kospi_series   else [],
            'kosdaq':  kosdaq_series[-30:] if kosdaq_series  else [],
            'usdkrw':  usdkrw_series[-30:] if usdkrw_series else [],
            'bond_3y': bond_series[-30:]   if bond_series    else [],
            'vix':     vix_series[-30:]    if vix_series     else [],
            'sp500':   sp500_series[-30:]  if sp500_series   else [],
            'nasdaq':  nq_series[-30:]     if nq_series      else [],
            'oil':     oil_series[-30:]    if oil_series     else [],
            'us10y':   us10y_series[-30:]  if us10y_series   else [],
        },
    }


# ─────────────────────────────────────────────────────────────────
# 라우트
# ─────────────────────────────────────────────────────────────────

@router.get('/macro_dashboard', dependencies=[Depends(require_login)])
def macro_dashboard_page(request: Request):
    return render(request, 'stock/macro_dashboard.html')


@router.get('/api/macro_dashboard', dependencies=[Depends(api_require_login)])
async def api_macro_dashboard():
    now = time.time()
    async with _MACRO_LOCK:
        if _MACRO_CACHE['data'] is None or now - _MACRO_CACHE['ts'] > _MACRO_TTL:
            try:
                data = await asyncio.to_thread(_build_macro_data)
            except Exception as e:
                logger.error(f'[macro] 데이터 수집 실패: {e}', exc_info=True)
                return JSONResponse({'ok': False, 'error': '거시지표 조회 중 오류가 발생했습니다.'}, status_code=500)
            _MACRO_CACHE['data'] = data
            _MACRO_CACHE['ts']   = now
        else:
            data = _MACRO_CACHE['data']

    return JSONResponse(data)
