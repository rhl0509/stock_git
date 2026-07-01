from fastapi import APIRouter, Request, Depends, Body
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from kiwoom_client import kiwoom, fetch_market_session
import urllib.request
import urllib.error
import json
import logging
import re
import time as _time
import asyncio
import concurrent.futures

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_CACHE_MAX_KEYS = 3000  # 코드별 캐시 상한 — 무한 메모리 증가 방지


def _cache_put(cache: dict, key, value):
    """TTL 캐시에 저장. 상한 초과 시 가장 오래된 항목부터 제거."""
    if len(cache) >= _CACHE_MAX_KEYS:
        for k in sorted(cache, key=lambda k: cache[k].get('ts', 0))[:_CACHE_MAX_KEYS // 10]:
            cache.pop(k, None)
    cache[key] = value


_NAVER_CACHE     = {}
_NAVER_CACHE_TTL = 3600

_NAVER_THEME_RATE_CACHE: dict = {"data": None, "ts": 0.0}
_NAVER_THEME_RATE_TTL = 600   # 10분 캐시

_NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://m.stock.naver.com/",
    "Accept":  "application/json, text/plain, */*",
}


def _safe_naver_float(val) -> float:
    try:
        if val is None or val == '' or val == 'N/A':
            return 0.0
        return float(str(val).replace(',', '').strip())
    except Exception:
        return 0.0


def _fetch_naver_stock(code: str) -> dict:
    cached = _NAVER_CACHE.get(code)
    if cached and _time.time() - cached['ts'] < _NAVER_CACHE_TTL:
        return cached['data']
    result = {"per": 0.0, "pbr": 0.0, "eps": 0, "bps": 0,
              "foreign_ratio": 0.0, "dividend": 0.0, "source": "naver"}
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
        result["per"]           = _safe_naver_float(raw.get('per') or raw.get('PER') or raw.get('forwardPer'))
        result["pbr"]           = _safe_naver_float(raw.get('pbr') or raw.get('PBR'))
        result["eps"]           = int(_safe_naver_float(raw.get('eps') or raw.get('EPS')))
        result["bps"]           = int(_safe_naver_float(raw.get('bps') or raw.get('BPS')))
        result["foreign_ratio"] = _safe_naver_float(raw.get('foreignRatio') or raw.get('foreignHoldingRate'))
        result["dividend"]      = _safe_naver_float(raw.get('dividendYield') or raw.get('dividend'))
    except urllib.error.HTTPError as e:
        logger.warning(f"[Naver] {code} HTTP 오류: {e.code}")
    except Exception as e:
        logger.warning(f"[Naver] {code} 조회 오류: {e}")
    _cache_put(_NAVER_CACHE, code, {"data": result, "ts": _time.time()})
    return result


_NAVER_PRICE_CACHE: dict = {}
_NAVER_PRICE_TTL = 60


def _fetch_naver_price(code: str) -> int | None:
    cached = _NAVER_PRICE_CACHE.get(code)
    if cached and _time.time() - cached['ts'] < _NAVER_PRICE_TTL:
        return cached['price']
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode('utf-8'))
        price_str = (raw.get('closePrice') or raw.get('currentPrice')
                     or raw.get('price') or raw.get('stockPrice'))
        if price_str:
            price = int(str(price_str).replace(',', '').strip())
            _cache_put(_NAVER_PRICE_CACHE, code, {"price": price, "ts": _time.time()})
            return price
    except Exception as e:
        logger.warning(f"[Naver] {code} 현재가 조회 실패: {e}")
    return None


_NAVER_FULL_CACHE: dict = {}
_NAVER_FULL_TTL = 60


def _fetch_naver_full(code: str) -> dict | None:
    cached = _NAVER_FULL_CACHE.get(code)
    if cached and _time.time() - cached['ts'] < _NAVER_FULL_TTL:
        return cached['data']

    def _to_int(s):
        try: return int(re.sub(r'[^\d]', '', str(s)) or 0)
        except: return 0

    def _to_float(s):
        try: return float(re.sub(r'[^\d.]', '', str(s)) or 0)
        except: return 0.0

    def _parse_mcap(s):
        s = str(s).replace(',', '')
        jo = re.search(r'(\d+)조', s)
        eok = re.search(r'(\d+)억', s)
        won = 0
        if jo:  won += int(jo.group(1)) * 1_000_000_000_000
        if eok: won += int(eok.group(1)) * 100_000_000
        return won // 1_000_000

    def _get_integration():
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def _get_basic():
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        req = urllib.request.Request(url, headers=_NAVER_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_int = ex.submit(_get_integration)
            f_bas = ex.submit(_get_basic)
            raw   = f_int.result(timeout=10)
            basic = f_bas.result(timeout=10)

        info   = {item['code']: item['value'] for item in raw.get('totalInfos', [])}
        price  = _to_int(basic.get('closePrice', 0))
        change = _to_int(basic.get('compareToPreviousClosePrice', 0))
        rate   = float(basic.get('fluctuationsRatio', 0) or 0)
        data = {
            "code": code, "name": raw.get('stockName', code),
            "price": price, "change": change, "rate": rate,
            "volume": _to_int(info.get('accumulatedTradingVolume', 0)),
            "open":   _to_int(info.get('openPrice', 0)),
            "high":   _to_int(info.get('highPrice', 0)),
            "low":    _to_int(info.get('lowPrice', 0)),
            "market_cap":    _parse_mcap(info.get('marketValue', '0')),
            "per":           _to_float(info.get('per', 0)),
            "pbr":           _to_float(info.get('pbr', 0)),
            "eps":           _to_int(info.get('eps', 0)),
            "bps":           _to_int(info.get('bps', 0)),
            "roe":           0.0,
            "dividend":      _to_float(info.get('dividendYieldRatio', 0)),
            "week52_high":   _to_int(info.get('highPriceOf52Weeks', 0)),
            "week52_low":    _to_int(info.get('lowPriceOf52Weeks', 0)),
            "foreign_ratio": _to_float(info.get('foreignRate', 0)),
            "shares":        0,
            "price_source":  "naver(지연)",
            "stock_end_type": basic.get('stockEndType', 'stock'),
        }
        _cache_put(_NAVER_FULL_CACHE, code, {"data": data, "ts": _time.time()})
        return data
    except Exception as e:
        logger.warning(f"[Naver] {code} 전체 조회 실패: {e}")
        return None


def _fetch_naver_theme_rates() -> dict:
    """네이버 증권 테마 페이지 HTML 파싱 (전체 페이지) → {테마명: 등락률} 반환."""
    cached = _NAVER_THEME_RATE_CACHE
    if cached["data"] is not None and _time.time() - cached["ts"] < _NAVER_THEME_RATE_TTL:
        return cached["data"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://finance.naver.com/",
    }
    _row_pat = re.compile(
        r'class="col_type1"><a[^>]+>([^<]+)</a></td>\s*'
        r'<td[^>]*col_type2[^>]*>.*?<span[^>]*>\s*([-+]?\d+\.\d+)%',
        re.DOTALL
    )
    result = {}
    try:
        for page in range(1, 15):
            url = f"https://finance.naver.com/sise/theme.naver?page={page}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as r:
                body = r.read()
            text = body.decode("euc-kr", errors="ignore")
            rows = _row_pat.findall(text)
            if not rows:
                break
            before = len(result)
            for name, rate in rows:
                result[name.strip()] = float(rate)
            if len(result) == before:  # 마지막 페이지 반복 감지
                break
            _time.sleep(0.1)
        logger.warning(f"[Naver Theme] {len(result)}개 테마 등락률 로드")
        cached["data"] = result
        cached["ts"] = _time.time()
        return result
    except Exception as e:
        logger.warning(f"[Naver Theme] 스크래핑 실패: {e}")
        return cached["data"] or {}


@router.get('/kiwoom/session')
def get_session():
    return fetch_market_session()


@router.get('/kiwoom/price/{code}')
def get_kiwoom_price(code: str):
    try:
        if not kiwoom.market_data_ready():
            data = _fetch_naver_full(code)
            if not data:
                return JSONResponse({"error": "데이터를 가져오지 못했습니다."}, status_code=404)
            return data
        data = kiwoom.get_stock_price(code)
        if data is None:
            return JSONResponse({"error": "데이터를 가져오지 못했습니다."}, status_code=404)
        return data
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/kiwoom/best/price/{code}')
async def get_best_price(code: str):
    try:
        if kiwoom.market_data_ready():
            data = kiwoom.get_best_price(code)
            if data:
                return data
        price = await asyncio.to_thread(_fetch_naver_price, code)
        if price:
            return {"code": code, "price": price, "price_source": "naver"}
        return JSONResponse({"error": "시세 조회 실패 (키움 미연결, 네이버 오류)"}, status_code=404)
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/kiwoom/info/{code}')
def get_kiwoom_info(code: str):
    try:
        if not kiwoom.market_data_ready():
            return JSONResponse({"error": "시세 소스(KIS) 미설정"}, status_code=503)
        data = kiwoom.get_stock_info(code)
        if data is None:
            return JSONResponse({"error": "데이터를 가져오지 못했습니다."}, status_code=404)
        return data
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.post('/kiwoom/prices')
def get_kiwoom_prices(request: Request, body: dict = Body(default={})):
    try:
        if not kiwoom.market_data_ready():
            return JSONResponse({"error": "시세 소스(KIS) 미설정"}, status_code=503)
        codes  = body.get('codes', [])
        results = []
        for code in codes[:20]:
            data = kiwoom.get_stock_price(code)
            if data:
                results.append(data)
        return results
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/kiwoom/ohlcv/{code}')
def get_ohlcv(code: str, request: Request):
    try:
        if not kiwoom.market_data_ready():
            return JSONResponse({"error": "시세 소스(KIS) 미설정"}, status_code=503)
        count = min(int(request.query_params.get('count', 80)), 600)
        df    = kiwoom.get_ohlcv(code, count=count)
        if df is None or df.empty:
            return JSONResponse({"error": "OHLCV 데이터를 가져오지 못했습니다."}, status_code=404)
        data = [{"date": idx.strftime("%Y-%m-%d"), "open": int(row["open"]),
                 "high": int(row["high"]), "low": int(row["low"]),
                 "close": int(row["close"]), "volume": int(row["volume"])}
                for idx, row in df.iterrows()]
        return {"code": code, "count": len(data), "data": data}
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/stock/naver/info/{code}')
def naver_stock_info(code: str):
    try:
        return _fetch_naver_stock(code)
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.post('/stock/naver/info/batch')
def naver_stock_info_batch(request: Request, body: dict = Body(default={})):
    try:
        codes   = body.get('codes', [])
        results = {}
        for code in codes[:50]:
            results[code] = _fetch_naver_stock(code)
            _time.sleep(0.1)
        return {"results": results}
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/naver/themes')
async def get_naver_themes():
    """네이버 증권 테마 목록 (전체 등락률 포함). 히트맵/랭킹 전용."""
    try:
        rates = await asyncio.to_thread(_fetch_naver_theme_rates)
        themes = [
            {"theme_name": name, "rate": rate, "theme_code": f"naver_{i}"}
            for i, (name, rate) in enumerate(rates.items())
        ]
        themes.sort(key=lambda t: t["rate"], reverse=True)
        return {"count": len(themes), "themes": themes, "source": "naver"}
    except Exception as e:
        logger.error(f'[kiwoom] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
