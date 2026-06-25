"""
global_features.py — yfinance 글로벌 지수 피처 (전 종목 공통).
GLOBAL_COLS = sp500_ret_1d, sp500_ret_5d, nasdaq_ret_1d, vix_level, oil_ret_20d, us_10y
캐시: data/cache/global/global.json (1시간)
"""
import json, logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger    = logging.getLogger(__name__)
ROOT      = Path(__file__).parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'global'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_HOURS = 1
CACHE_FILE  = CACHE_DIR / 'global.json'

GLOBAL_COLS = [
    "sp500_ret_1d", "sp500_ret_5d", "nasdaq_ret_1d",
    "vix_level", "oil_ret_20d", "us_10y",
]
_ZERO = {c: 0.0 for c in GLOBAL_COLS}


def _load_cache():
    if not CACHE_FILE.exists():
        return None
    age = (datetime.now() - datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)).total_seconds()
    if age > CACHE_HOURS * 3600:
        return None
    try:
        return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_cache(data: dict):
    try:
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _pct_ret(series: pd.Series, n: int) -> float:
    s = series.dropna()
    if len(s) <= n:
        return 0.0
    return float((s.iloc[-1] - s.iloc[-n - 1]) / (abs(s.iloc[-n - 1]) + 1e-9))


def get_global_features() -> dict:
    """
    글로벌 지수 피처 6개.
    yfinance, 1시간 캐시.
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        end   = datetime.now()
        start = end - timedelta(days=60)

        symbols = {"^GSPC": "sp500", "^IXIC": "nasdaq",
                   "^VIX": "vix", "CL=F": "oil", "^TNX": "us10y"}
        data = {}
        for sym, key in symbols.items():
            try:
                raw = yf.Ticker(sym).history(start=start, end=end, auto_adjust=False)
                if raw is not None and not raw.empty:
                    data[key] = raw["Close"].dropna()
            except Exception:
                pass

        result = _ZERO.copy()
        if "sp500"  in data:
            result["sp500_ret_1d"]  = _pct_ret(data["sp500"],  1)
            result["sp500_ret_5d"]  = _pct_ret(data["sp500"],  5)
        if "nasdaq" in data:
            result["nasdaq_ret_1d"] = _pct_ret(data["nasdaq"], 1)
        if "vix"    in data:
            result["vix_level"]     = float(data["vix"].iloc[-1])
        if "oil"    in data:
            result["oil_ret_20d"]   = _pct_ret(data["oil"],   20)
        if "us10y"  in data:
            result["us_10y"]        = float(data["us10y"].iloc[-1])

        _save_cache(result)
        return result

    except Exception as e:
        logger.debug(f"[global] {e}")
        _save_cache(_ZERO)
        return _ZERO


# ─── US 섹터 ETF 스냅샷 (UI 표시용, ML 피처 아님) ───────────────────────────

_US_SECTORS = [
    ("XLK",  "테크",      "tech"),
    ("XLF",  "금융",      "fin"),
    ("XLE",  "에너지",    "energy"),
    ("XLV",  "헬스케어",  "health"),
    ("XLY",  "소비재",    "cons"),
    ("XLI",  "산업재",    "indus"),
    ("XLC",  "통신",      "comm"),
    ("XLB",  "소재",      "materials"),
    ("XLU",  "유틸리티",  "util"),
    ("XLRE", "리츠",      "reit"),
]

_SECTOR_CACHE_FILE = CACHE_DIR / 'us_sectors.json'


def get_us_sector_snapshot() -> dict:
    """
    미국 섹터 ETF 10개의 1일·5일 수익률과 주요 지수 현황.
    yfinance, 1시간 캐시.
    반환 예:
      {
        "updated_at": "2026-05-23 14:30",
        "indices": {"sp500_1d": 0.5, "nasdaq_1d": -0.2, "vix": 18.5},
        "sectors": [{"name": "테크", "ticker": "XLK", "ret_1d": 1.2, "ret_5d": 2.3}, ...]
      }
    """
    if _SECTOR_CACHE_FILE.exists():
        age = (datetime.now() - datetime.fromtimestamp(
            _SECTOR_CACHE_FILE.stat().st_mtime)).total_seconds()
        if age <= CACHE_HOURS * 3600:
            try:
                return json.loads(_SECTOR_CACHE_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass

    try:
        import yfinance as yf
        end   = datetime.now()
        start = end - timedelta(days=30)

        tickers = [t for t, _, _ in _US_SECTORS] + ["^GSPC", "^IXIC", "^VIX"]
        raw = yf.download(tickers, start=start, end=end,
                          auto_adjust=False, progress=False)
        close = raw["Close"] if "Close" in raw.columns else raw

        def _ret(col, n):
            if col not in close.columns:
                return 0.0
            s = close[col].dropna()
            if len(s) <= n:
                return 0.0
            return round(float((s.iloc[-1] - s.iloc[-n - 1]) / (abs(s.iloc[-n - 1]) + 1e-9) * 100), 2)

        indices = {
            "sp500_1d":  _ret("^GSPC", 1),
            "sp500_5d":  _ret("^GSPC", 5),
            "nasdaq_1d": _ret("^IXIC", 1),
            "vix":       round(float(close["^VIX"].dropna().iloc[-1]), 2)
                         if "^VIX" in close.columns and not close["^VIX"].dropna().empty else 0.0,
        }

        sectors = []
        for ticker, name, _ in _US_SECTORS:
            sectors.append({
                "name":   name,
                "ticker": ticker,
                "ret_1d": _ret(ticker, 1),
                "ret_5d": _ret(ticker, 5),
            })

        result = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "indices":    indices,
            "sectors":    sectors,
        }
        try:
            _SECTOR_CACHE_FILE.write_text(
                json.dumps(result, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        return result

    except Exception as e:
        logger.debug(f"[global/sectors] {e}")
        return {"updated_at": "", "indices": {}, "sectors": []}


# ─── 한국 KOSPI 업종 스냅샷 (Naver Finance 스크래핑) ────────────────────────

_KR_SECTOR_CACHE_FILE = CACHE_DIR / 'kr_sectors.json'


_KR_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
_RE_NO   = __import__('re').compile(r'no=(\d+)')
_RE_CODE = __import__('re').compile(r'code=([A-Z0-9]+)')


def get_kr_sector_snapshot() -> dict:
    """
    Naver Finance 업종시세 스크래핑 → KOSPI 업종별 등락률 + no(상세 페이지 ID).
    1시간 캐시.
    반환: {"updated_at": "...", "sectors": [{"name": "전기전자", "change": 2.34, "stocks": 111, "no": 4}, ...]}
    """
    if _KR_SECTOR_CACHE_FILE.exists():
        age = (datetime.now() - datetime.fromtimestamp(
            _KR_SECTOR_CACHE_FILE.stat().st_mtime)).total_seconds()
        if age <= CACHE_HOURS * 3600:
            try:
                return json.loads(_KR_SECTOR_CACHE_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass

    try:
        import requests
        from bs4 import BeautifulSoup

        r = requests.get(
            'https://finance.naver.com/sise/sise_group.naver?type=upjong',
            headers=_KR_HEADERS, timeout=8)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')

        sectors = []
        for row in soup.select('table.type_1 tr'):
            tds = row.select('td')
            if len(tds) < 4:
                continue
            a = tds[0].find('a')
            name = tds[0].get_text(strip=True)
            no = None
            if a:
                m = _RE_NO.search(a.get('href', ''))
                if m:
                    no = int(m.group(1))
            chg_txt = tds[1].get_text(strip=True).replace('%', '').replace('+', '').replace(',', '')
            stocks_txt = tds[2].get_text(strip=True).replace(',', '')
            if not name or not chg_txt:
                continue
            try:
                sectors.append({
                    "name":    name,
                    "change":  round(float(chg_txt), 2),
                    "stocks":  int(stocks_txt) if stocks_txt.isdigit() else 0,
                    "no":      no,
                })
            except ValueError:
                continue

        sectors = [s for s in sectors if s.get("no") is not None]
        if not sectors:
            raise ValueError("empty sector list")

        result = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "sectors":    sectors,
        }
        try:
            _KR_SECTOR_CACHE_FILE.write_text(
                json.dumps(result, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        return result

    except Exception as e:
        logger.debug(f"[global/kr_sectors] {e}")
        return {"updated_at": "", "sectors": []}


_KR_STOCKS_CACHE_DIR = CACHE_DIR / 'kr_sector_stocks'
_KR_STOCKS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_kr_sector_stocks(sector_no: int) -> list:
    """
    Naver Finance 업종 상세 종목 리스트.
    반환: [{"name": "삼성전자", "code": "005930", "price": "83000",
             "change_pct": "+1.23%", "change_dir": "up"}, ...]
    30분 캐시.
    """
    cache_file = _KR_STOCKS_CACHE_DIR / f'{sector_no}.json'
    if cache_file.exists():
        age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds()
        if age <= 1800:
            try:
                return json.loads(cache_file.read_text(encoding='utf-8'))
            except Exception:
                pass

    try:
        import requests
        from bs4 import BeautifulSoup

        url = (f'https://finance.naver.com/sise/sise_group_detail.naver'
               f'?type=upjong&no={sector_no}')
        r = requests.get(url, headers=_KR_HEADERS, timeout=8)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')

        table = soup.find('table', class_='type_5')
        if not table:
            return []

        stocks = []
        for row in table.find_all('tr'):
            tds = row.find_all('td')
            if len(tds) < 4:
                continue
            a = tds[0].find('a')
            if not a:
                continue
            m = _RE_CODE.search(a.get('href', ''))
            if not m:
                continue
            code = m.group(1)
            name = a.get_text(strip=True).replace('*', '').strip()
            price = tds[1].get_text(strip=True).replace(',', '')
            chg_pct = tds[3].get_text(strip=True)  # e.g. "+1.23%"
            chg_dir = 'up' if chg_pct.startswith('+') else ('down' if chg_pct.startswith('-') else 'flat')
            stocks.append({
                "name":       name,
                "code":       code,
                "price":      price,
                "change_pct": chg_pct,
                "change_dir": chg_dir,
            })

        try:
            cache_file.write_text(json.dumps(stocks, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        return stocks

    except Exception as e:
        logger.debug(f"[global/kr_sector_stocks] no={sector_no}: {e}")
        return []


if __name__ == '__main__':
    print(get_global_features())
    import pprint
    pprint.pprint(get_us_sector_snapshot())
    pprint.pprint(get_kr_sector_snapshot())
