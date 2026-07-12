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

# ECOS 통계표 코드 (라이브 우선 시도용 — 아래 3개는 2026-07 개편으로 폐지됨)
INDICATORS = {
    "kospi":    ("901Y014", "0001000", "D"),    # KOSPI 일별 (D주기 폐지 → 폴백)
    "usdkrw":   ("731Y003", "0000001", "D"),    # 원/달러 일별 (아이템 폐지 → 폴백)
    "call_rate":("722Y001", "01011000","D"),    # 콜금리 일별 (아이템 폐지 → 폴백)
    "cpi":      ("901Y009", "0",       "M"),    # CPI 월별
    "bond_3y":  ("817Y002", "010190000","D"),   # 국고채 3년 일별 (정상 — 라이브 유지)
}

# ── ECOS 폴백 코드 ──────────────────────────────────────────────────────────
# 2026-07 실측(macro_history.py와 동일): INDICATORS의 3개가 ECOS 개편으로
# INFO-200(데이터 없음) → 라이브 캐시가 0.0으로 무효화되던 버그. 검증된 대체 코드로 폴백.
#   kospi     901Y014/0001000  → 802Y001/0001000   (KOSPI지수 D, 1995~)
#   usdkrw    731Y003/0000001  → 731Y003/0000003   (원/달러 종가 15:30, 1990~)
#   call_rate 722Y001/01011000 → 817Y002/010101000 (콜금리 1일 전체거래, 1995~)
# 조회는 라이브(INDICATORS) 코드를 먼저 시도하고, 비면 아래 폴백을 쓴다.
_ECOS_FALLBACKS = {
    "kospi":     ("802Y001", "0001000",   "D"),
    "usdkrw":    ("731Y003", "0000003",   "D"),
    "call_rate": ("817Y002", "010101000", "D"),
}


def _fetch_with_fallback(name: str, n: int = 30):
    """INDICATORS[name] 라이브 코드 우선, 빈 응답이면 _ECOS_FALLBACKS로 재시도."""
    vals = _fetch_indicator(*INDICATORS[name], n=n)
    if not vals and name in _ECOS_FALLBACKS:
        logger.info(f"[bok] {name}: 라이브 코드 실패 → 폴백 {_ECOS_FALLBACKS[name][0]}")
        vals = _fetch_indicator(*_ECOS_FALLBACKS[name], n=n)
    return vals


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
    kospi = _fetch_with_fallback("kospi", n=30)
    if kospi and len(kospi) >= 20:
        result["kospi_ret_20d"] = round(
            (kospi[-1] - kospi[-20]) / kospi[-20], 4)
        ma20 = sum(kospi[-20:]) / 20
        result["kospi_trend"]   = round((kospi[-1] - ma20) / ma20, 4)
    else:
        result["kospi_ret_20d"] = 0.0
        result["kospi_trend"]   = 0.0

    # 환율
    usd = _fetch_with_fallback("usdkrw", n=30)
    if usd and len(usd) >= 20:
        result["usdkrw_ret_20d"] = round((usd[-1] - usd[-20]) / usd[-20], 4)
    else:
        result["usdkrw_ret_20d"] = 0.0

    # 금리
    bond = _fetch_indicator(*INDICATORS["bond_3y"], n=5)
    result["bond_3y"] = float(bond[-1]) if bond else 0.0

    call = _fetch_with_fallback("call_rate", n=5)
    result["call_rate"] = float(call[-1]) if call else 0.0

    # 전 지표 조회 실패(전부 0.0)면 캐시에 저장하지 않는다 — 일시적 실패가
    # 24h 동안 0.0으로 굳는 것을 방지(macro_history 가드와 동일 취지).
    if any(v != 0.0 for v in result.values()):
        _save_cache(result)
    else:
        logger.warning("[bok] 전 거시지표 0.0 (조회 실패) → 캐시 저장 안 함")
    return result


MACRO_COLS = [
    "kospi_ret_20d", "kospi_trend",
    "usdkrw_ret_20d", "bond_3y", "call_rate",
]


if __name__ == '__main__':
    print(get_macro_features())