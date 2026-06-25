"""
dart_client.py — 금감원 DART 공시 조회.
무료 무제한.

기능:
  - 최근 N일 공시 조회 (회사별)
  - 공시 유형 분류 (실적/증자/감자/배당/기타)
  - 피처: 최근 30일 공시 건수, 긍정/부정 이벤트 플래그

캐시: data/cache/dart/{ticker}.json (6시간)
"""
import os, json, logging, time
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

import requests

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'dart'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DART_KEY = os.getenv("DART_API_KEY", "")
CACHE_HOURS = 6

# 회사코드(corp_code) 매핑: 종목코드 → DART corp_code
# 최초 1회 전체 매핑 다운로드 후 로컬 저장
CORP_MAP_PATH = ROOT / 'data' / 'dart_corp_map.json'


def _load_corp_map() -> dict:
    """종목코드 ↔ corp_code 매핑 반환 (최초 호출 시 다운로드)."""
    if CORP_MAP_PATH.exists():
        try:
            return json.loads(CORP_MAP_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return _download_corp_map()


def _download_corp_map() -> dict:
    """DART corp_code ZIP 다운로드 → 매핑 저장."""
    if not DART_KEY:
        logger.warning("[dart] API 키 없음")
        return {}
    try:
        import io, zipfile
        import xml.etree.ElementTree as ET
        url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_KEY}"
        r = requests.get(url, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_bytes = z.read(z.namelist()[0])
        root = ET.fromstring(xml_bytes)
        mapping = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code  = (item.findtext("corp_code")  or "").strip()
            if stock_code and corp_code:
                mapping[stock_code] = corp_code
        CORP_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        CORP_MAP_PATH.write_text(
            json.dumps(mapping, ensure_ascii=False), encoding='utf-8')
        logger.info(f"[dart] corp_map 저장: {len(mapping)}개")
        return mapping
    except Exception as e:
        logger.error(f"[dart] corp_map 다운로드 실패: {e}")
        return {}


# ═════════════════════════════════════════════════════════════════════════
# 공시 유형 분류
# ═════════════════════════════════════════════════════════════════════════

POSITIVE_KEYWORDS = [
    "흑자전환", "실적호전", "매출증가", "자사주", "무상증자",
    "배당", "수주", "계약", "특허", "신제품", "인수", "합병(합병법인)",
    "상향", "돌파", "기록", "최대", "최고",
]

NEGATIVE_KEYWORDS = [
    "적자전환", "실적악화", "매출감소", "유상증자", "감자",
    "소송", "제재", "과징금", "상장폐지", "관리종목",
    "거래정지", "횡령", "배임", "분식회계", "하향", "감소",
]


def _classify_report(title: str) -> str:
    """공시 제목 → 분류"""
    t = title
    if any(k in t for k in POSITIVE_KEYWORDS):
        return "positive"
    if any(k in t for k in NEGATIVE_KEYWORDS):
        return "negative"
    return "neutral"


# ═════════════════════════════════════════════════════════════════════════
# 공시 조회
# ═════════════════════════════════════════════════════════════════════════

def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def _load_cache(code: str):
    p = _cache_path(code)
    if not p.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    if age.total_seconds() > CACHE_HOURS * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_cache(code: str, data):
    try:
        _cache_path(code).write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def get_recent_disclosures(code: str, days: int = 30) -> list[dict]:
    """
    최근 N일 공시 목록 반환.
    반환: [{date, title, category}, ...]
    """
    cached = _load_cache(code)
    if cached is not None:
        return cached

    if not DART_KEY:
        return []

    corp_map = _load_corp_map()
    corp_code = corp_map.get(code)
    if not corp_code:
        return []

    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        url = (
            "https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={DART_KEY}&corp_code={corp_code}"
            f"&bgn_de={start}&end_de={end}&page_count=50"
        )
        r = requests.get(url, timeout=5)
        data = r.json()
        items = data.get("list", []) or []
        out = [
            {
                "date":     it.get("rcept_dt", ""),
                "title":    it.get("report_nm", ""),
                "category": _classify_report(it.get("report_nm", "")),
                "rcept_no": it.get("rcept_no", ""),
            }
            for it in items
        ]
        _save_cache(code, out)
        return out
    except Exception as e:
        logger.debug(f"[dart] {code}: {e}")
        return []


def get_disclosure_features(code: str, days: int = 90) -> dict:
    """
    피처 빌드용 공시 지표.

    반환:
      n_disclosures_30d    : 30일 공시 건수
      n_positive_30d       : 긍정 공시 건수
      n_negative_30d       : 부정 공시 건수
      disclosure_score     : (긍정 - 부정) / (총 + 1)
      days_since_disclosure: 가장 최근 공시로부터 경과 일수 (없으면 999)
    """
    items = get_recent_disclosures(code, days)

    days_since = 999
    if items:
        dates = [it.get("date", "") for it in items if it.get("date")]
        if dates:
            dates.sort(reverse=True)
            try:
                last = datetime.strptime(dates[0], "%Y%m%d")
                days_since = max(0, (datetime.now() - last).days)
            except Exception:
                pass

    if not items:
        return {
            "n_disclosures_30d":     0,
            "n_positive_30d":        0,
            "n_negative_30d":        0,
            "disclosure_score":      0.0,
            "days_since_disclosure": days_since,
        }
    n_total    = len(items)
    n_positive = sum(1 for it in items if it["category"] == "positive")
    n_negative = sum(1 for it in items if it["category"] == "negative")
    score      = (n_positive - n_negative) / (n_total + 1)
    return {
        "n_disclosures_30d":     n_total,
        "n_positive_30d":        n_positive,
        "n_negative_30d":        n_negative,
        "disclosure_score":      round(score, 4),
        "days_since_disclosure": days_since,
    }


DISCLOSURE_COLS = [
    "n_disclosures_30d", "n_positive_30d",
    "n_negative_30d",    "disclosure_score",
    "days_since_disclosure",
]


# ─────────────────────────────────────────────────────────────────
# 전체 시장 공시 조회 (보고서 에이전트용)
# ─────────────────────────────────────────────────────────────────

_MARKET_CACHE_FILE = CACHE_DIR / "_market_all.json"
_MARKET_CACHE_HOURS = 6


def get_market_disclosures(days: int = 7, page_count: int = 40) -> list[dict]:
    """
    전체 시장 최근 N일 공시 조회 (종목 코드 없이).
    보고서 에이전트의 일간/주간/월간 공시 섹션에 사용.

    반환: [{corp_name, report_nm, rcept_no, rcept_dt, category}, ...]
    """
    # 캐시 확인 (days와 무관하게 최신 결과 재사용)
    if _MARKET_CACHE_FILE.exists():
        age = (datetime.now() - datetime.fromtimestamp(
            _MARKET_CACHE_FILE.stat().st_mtime)).total_seconds()
        if age < _MARKET_CACHE_HOURS * 3600:
            try:
                cached = json.loads(_MARKET_CACHE_FILE.read_text(encoding="utf-8"))
                # days 필터 적용 후 반환
                cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
                return [it for it in cached if it.get("rcept_dt", "") >= cutoff]
            except Exception:
                pass

    if not DART_KEY:
        logger.warning("[dart] API 키 없음 — 전체 공시 조회 불가")
        return []

    try:
        end   = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")  # 항상 30일치 캐시
        url = (
            "https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={DART_KEY}"
            f"&bgn_de={start}&end_de={end}"
            f"&page_count={page_count}"
        )
        r = requests.get(url, timeout=10)
        data = r.json()
        items = data.get("list", []) or []
        out = [
            {
                "corp_name": it.get("corp_name", ""),
                "report_nm": it.get("report_nm", ""),
                "rcept_no":  it.get("rcept_no", ""),
                "rcept_dt":  it.get("rcept_dt", ""),
                "category":  _classify_report(it.get("report_nm", "")),
            }
            for it in items
        ]
        # 30일치 전체 캐시 저장
        _MARKET_CACHE_FILE.write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8")
        # days 필터 후 반환
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        return [it for it in out if it.get("rcept_dt", "") >= cutoff]
    except Exception as e:
        logger.error(f"[dart] 전체 공시 조회 실패: {e}")
        return []


if __name__ == '__main__':
    print(get_disclosure_features("005930"))