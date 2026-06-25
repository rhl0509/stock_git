"""
routes/stock_data.py — 주식 원본 데이터 API
"""

import logging
import re
import html as _html
import json
import urllib.request
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
import pandas as pd

from korea_stock_data import KoreaStockData

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_data = KoreaStockData(cache_dir='./cache/stock_data')


def _date_range(days: int) -> tuple[str, str]:
    end = datetime.now()
    start = end - timedelta(days=days)
    return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')


def _df_to_records(df: pd.DataFrame) -> list:
    if df is None or df.empty:
        return []
    out = df.reset_index()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime('%Y-%m-%d')
    return out.to_dict(orient='records')


def _ok(payload: dict):
    return {"ok": True, **payload}


def _err(msg: str, status: int = 500):
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


@router.get('/stock-data/quote/{code}')
def get_quote(code: str, request: Request):
    days = int(request.query_params.get('days', 60))
    try:
        start, end = _date_range(days)
        df = _data.krx.ohlcv(code, start, end)
        return _ok({"code": code, "data": _df_to_records(df)})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/valuation/{code}')
def get_valuation(code: str, request: Request):
    days = int(request.query_params.get('days', 60))
    try:
        start, end = _date_range(days)
        df = _data.krx.valuation(code, start, end)
        return _ok({"code": code, "data": _df_to_records(df)})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/flow/{code}')
def get_flow(code: str, request: Request):
    days = int(request.query_params.get('days', 60))
    try:
        start, end = _date_range(days)
        df = _data.krx.investor_flow(code, start, end)
        return _ok({"code": code, "data": _df_to_records(df)})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/short/{code}')
def get_short(code: str, request: Request):
    days = int(request.query_params.get('days', 60))
    try:
        start, end = _date_range(days)
        df = _data.krx.short_balance(code, start, end)
        return _ok({"code": code, "data": _df_to_records(df)})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/consensus/{code}')
def get_consensus(code: str):
    try:
        result = _data.naver.consensus(code)
        return _ok(result)
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/financials/{code}')
def get_financials(code: str):
    try:
        fin = _data.fnguide.financials(code)
        out = {}
        for k, v in fin.items():
            if isinstance(v, pd.DataFrame):
                out[k] = _df_to_records(v)
            elif isinstance(v, str):
                out[k] = v
        return _ok({"code": code, "financials": out})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/macro')
def get_macro(request: Request):
    if _data.fred is None:
        return _err("FRED_API_KEY 미설정 — .env 파일에 추가 필요", 503)
    try:
        start = request.query_params.get('start', '2024-01-01')
        df = _data.fred.macro_panel(start=start)
        return _ok({"data": _df_to_records(df.tail(30))})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


@router.get('/stock-data/snapshot')
def get_snapshot(request: Request):
    date_str = request.query_params.get('date', datetime.now().strftime('%Y%m%d'))
    market   = request.query_params.get('market', 'ALL')
    try:
        df = _data.krx.fundamental_snapshot(date_str, market=market)
        return _ok({"date": date_str, "market": market, "data": _df_to_records(df)})
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


_NEWS_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Referer':         'https://finance.naver.com/',
}

@router.get('/stock-data/news/{code}')
def get_news(code: str, request: Request):
    limit = min(int(request.query_params.get('limit', 7)), 20)
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
        req = urllib.request.Request(url, headers=_NEWS_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            enc = r.headers.get_content_charset() or 'euc-kr'
            raw = r.read().decode(enc, errors='replace')

        links = re.findall(
            r'href="(/item/news_read\.naver\?[^"]+)"[^>]*>\s*([^<]{8,120})\s*</a>',
            raw
        )
        dates   = re.findall(r'<td class="date">\s*([^<]+)</td>', raw)
        presses = re.findall(r'<td class="info">([^<]*)</td>', raw)

        items = []
        for i, (href, raw_title) in enumerate(links):
            title = re.sub(r'\s+', ' ', _html.unescape(raw_title)).strip()
            if len(title) < 8:
                continue
            items.append({
                'title': title,
                'url':   'https://finance.naver.com' + href,
                'press': presses[i].strip() if i < len(presses) else '',
                'date':  dates[i].strip()   if i < len(dates)   else '',
            })
            if len(items) >= limit:
                break

        return items
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


_NAVER_HEADERS_ETF = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Referer':    'https://m.stock.naver.com/',
}

@router.get('/stock-data/etf-info/{code}')
def get_etf_info(code: str):
    try:
        req = urllib.request.Request(
            f'https://m.stock.naver.com/api/stock/{code}/integration',
            headers=_NAVER_HEADERS_ETF
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode('utf-8'))

        ki   = data.get('etfKeyIndicator') or {}
        info = {item['code']: item['value'] for item in data.get('totalInfos', [])}

        return {
            'nav':            ki.get('nav', 0),
            'deviation_rate': ki.get('deviationRate', 0),
            'deviation_sign': ki.get('deviationSign', ''),
            'issuer_name':    ki.get('issuerName', ''),
            'total_fee':      ki.get('totalFee', 0),
            'dividend_yield': ki.get('dividendYieldTtm', 0),
            'market_value':   ki.get('marketValue', ''),
            'total_nav':      ki.get('totalNav', ''),
            'return_1m':      ki.get('returnRate1m', 0),
            'return_3m':      ki.get('returnRate3m', 0),
            'return_1y':      ki.get('returnRate1y', 0),
            'benchmark':      info.get('etfBaseIdx', ''),
            'description':    data.get('description', ''),
        }
    except Exception as e:
        logger.error(f'[stock_data] {e}', exc_info=True)
        return _err('서버 오류가 발생했습니다.')


_MAJOR_ETFS = [
    {'code': '069500', 'name': 'KODEX 200',          'category': '시장지수'},
    {'code': '102110', 'name': 'TIGER 200',           'category': '시장지수'},
    {'code': '229200', 'name': 'KODEX 코스닥150',     'category': '시장지수'},
    {'code': '122630', 'name': 'KODEX 레버리지',      'category': '레버리지'},
    {'code': '252670', 'name': 'KODEX 200선물인버스2X','category': '인버스'},
    {'code': '091160', 'name': 'KODEX 반도체',        'category': '반도체'},
    {'code': '305720', 'name': 'KODEX 2차전지산업',   'category': '2차전지'},
    {'code': '139260', 'name': 'KODEX 바이오',        'category': '바이오'},
    {'code': '091180', 'name': 'KODEX 자동차',        'category': '자동차'},
    {'code': '266370', 'name': 'KODEX 미국나스닥100', 'category': '해외'},
    {'code': '381170', 'name': 'TIGER 미국S&P500',    'category': '해외'},
    {'code': '192090', 'name': 'TIGER 차이나CSI300',  'category': '해외'},
]

@router.get('/stock-data/major-etfs')
def get_major_etfs():
    import concurrent.futures

    def _fetch_one(etf):
        try:
            req = urllib.request.Request(
                f"https://m.stock.naver.com/api/stock/{etf['code']}/basic",
                headers=_NAVER_HEADERS_ETF
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read().decode('utf-8'))
            def _int(s):
                try: return int(str(s).replace(',', ''))
                except: return 0
            return {**etf,
                'price':  _int(d.get('closePrice', 0)),
                'change': _int(d.get('compareToPreviousClosePrice', 0)),
                'rate':   float(d.get('fluctuationsRatio', 0) or 0),
            }
        except Exception:
            return {**etf, 'price': 0, 'change': 0, 'rate': 0.0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_fetch_one, _MAJOR_ETFS))

    return results
