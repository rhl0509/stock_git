"""
bok_client.py — 한국은행 ECOS 거시 지표 조회.
무료 무제한.

지표:
  KOSPI 지수      : 901Y014 0001000
  원/달러 환율    : 731Y003 0000001
  콜금리(1일물)    : 722Y001 01011000
  CPI(소비자물가) : 901Y009 0
  국고채 3년      : 817Y002 010190000

캐시: data/cache/bok/macro.json (1일)
→ 거시지표는 일별 공통이므로 1개 파일에 캐싱.
"""
import os, json, logging
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

import requests

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'bok'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BOK_KEY = os.getenv("BOK_API_KEY", "")
CACHE_HOURS = 24
CACHE_FILE = CACHE_DIR / 'macro.json'

# ECOS 통계표 코드
INDICATORS = {
    "kospi":    ("901Y014", "0001000", "D"),    # KOSPI 일별
    "usdkrw":   ("731Y003", "0000001", "D"),    # 원/달러 일별
    "call_rate":("722Y001", "01011000","D"),    # 콜금리 일별
    "cpi":      ("901Y009", "0",       "M"),    # CPI 월별
    "bond_3y":  ("817Y002", "010190000","D"),   # 국고채 3년 일별
}


def _load_cache():
    if not CACHE_FILE.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)
    if age.total_seconds() > CACHE_HOURS * 3600:
        return None
    try:
        return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_cache(data: dict):
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def _fetch_indicator(stat_code: str, item: str, cycle: str, n: int = 30):
    """
    ECOS 데이터 조회 → 최근 N개 값 리스트.
    cycle: D(일) | M(월)
    """
    if not BOK_KEY:
        return []
    try:
        now = datetime.now()
        if cycle == "D":
            start = (now - timedelta(days=n * 2)).strftime("%Y%m%d")
            end   = now.strftime("%Y%m%d")
        else:  # M
            start = (now - timedelta(days=n * 31)).strftime("%Y%m")
            end   = now.strftime("%Y%m")

        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_KEY}/json/kr/"
            f"1/{n}/{stat_code}/{cycle}/{start}/{end}/{item}"
        )
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return []
        data = r.json()
        rows = data.get("StatisticSearch", {}).get("row", [])
        return [float(row.get("DATA_VALUE", 0)) for row in rows if row.get("DATA_VALUE")]
    except Exception as e:
        logger.debug(f"[bok] {stat_code}: {e}")
        return []


def get_macro_features() -> dict:
    """
    거시 피처 dict.
    모든 종목이 동일 값 공유 (시장 전체 상태).

    반환:
      kospi_ret_20d      : KOSPI 20일 수익률
      kospi_trend        : KOSPI 20일 이평 대비 현재가
      usdkrw_ret_20d     : 환율 20일 변화
      bond_3y            : 국고채 3년 현재
      call_rate          : 콜금리 현재
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    result = {}
    # KOSPI
    kospi = _fetch_indicator(*INDICATORS["kospi"], n=30)
    if kospi and len(kospi) >= 20:
        result["kospi_ret_20d"] = round(
            (kospi[-1] - kospi[-20]) / kospi[-20], 4)
        ma20 = sum(kospi[-20:]) / 20
        result["kospi_trend"]   = round((kospi[-1] - ma20) / ma20, 4)
    else:
        result["kospi_ret_20d"] = 0.0
        result["kospi_trend"]   = 0.0

    # 환율
    usd = _fetch_indicator(*INDICATORS["usdkrw"], n=30)
    if usd and len(usd) >= 20:
        result["usdkrw_ret_20d"] = round((usd[-1] - usd[-20]) / usd[-20], 4)
    else:
        result["usdkrw_ret_20d"] = 0.0

    # 금리
    bond = _fetch_indicator(*INDICATORS["bond_3y"], n=5)
    result["bond_3y"] = float(bond[-1]) if bond else 0.0

    call = _fetch_indicator(*INDICATORS["call_rate"], n=5)
    result["call_rate"] = float(call[-1]) if call else 0.0

    _save_cache(result)
    return result


MACRO_COLS = [
    "kospi_ret_20d", "kospi_trend",
    "usdkrw_ret_20d", "bond_3y", "call_rate",
]


if __name__ == '__main__':
    print(get_macro_features())