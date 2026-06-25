"""routes/trade_stats.py — 수출입 동향 (BOK ECOS + 관세청)."""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from routes.utils import require_login, require_login_smart
from templates_config import render

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

BOK_KEY     = os.getenv("BOK_API_KEY", "")
CUSTOMS_KEY = os.getenv("CUSTOMS_API_KEY", "")
CUSTOMS_BASE = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

_CACHE_DIR = Path("XGBoost_v2/data/cache/bok")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_FILE = _CACHE_DIR / "trade.json"
_CACHE_HOURS = 6


# ── 캐시 ─────────────────────────────────────────────────────────────

def _load_cache() -> dict | None:
    if not _CACHE_FILE.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime)
    if age.total_seconds() > _CACHE_HOURS * 3600:
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        # 섹터 데이터 없는 구버전 캐시 무효화
        if not data.get("sectors"):
            return None
        return data
    except Exception:
        return None


def _save_cache(data: dict):
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ── BOK ECOS 조회 ─────────────────────────────────────────────────────

def _fetch(stat_code: str, item_code: str, cycle: str = "M", n: int = 40) -> list[dict]:
    """BOK ECOS StatisticSearch API → row 리스트."""
    if not BOK_KEY:
        return []
    try:
        now = datetime.now()
        if cycle == "M":
            start = (now - timedelta(days=n * 32)).strftime("%Y%m")
            end   = now.strftime("%Y%m")
        else:
            start = (now - timedelta(days=n * 2)).strftime("%Y%m%d")
            end   = now.strftime("%Y%m%d")

        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_KEY}/json/kr/"
            f"1/{n}/{stat_code}/{cycle}/{start}/{end}/{item_code}"
        )
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return []
        return r.json().get("StatisticSearch", {}).get("row", [])
    except Exception as e:
        logger.debug(f"[trade] BOK {stat_code}/{item_code}: {e}")
        return []


def _fetch_country(item_code: str, n_months: int = 14) -> dict[str, dict]:
    """901Y121에서 국가별 수출/수입 데이터.

    T002 = 수출금액 (Korea → 상대국)
    T004 = 수입금액 (상대국 → Korea)
    반환: {date: {country_code: {"name": str, "value": float}}}
    """
    if not BOK_KEY:
        return {}
    try:
        now = datetime.now()
        start_m = (now - timedelta(days=n_months * 32)).strftime("%Y%m")
        end_m   = now.strftime("%Y%m")
        n_rows  = 600  # 30개국 × 14개월 + 여유
        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_KEY}/json/kr/"
            f"1/{n_rows}/901Y121/M/{start_m}/{end_m}/{item_code}"
        )
        rows = requests.get(url, timeout=18).json().get("StatisticSearch", {}).get("row", [])
        result: dict[str, dict] = {}
        for row in rows:
            t    = row.get("TIME", "")
            code = row.get("ITEM_CODE2", "")
            name = row.get("ITEM_NAME2", "")
            v    = _to_float(row)
            if t and code and v is not None:
                result.setdefault(t, {})[code] = {"name": name, "value": v}
        return result
    except Exception as e:
        logger.debug(f"[trade] 901Y121/{item_code}: {e}")
        return {}


def _to_float(row: dict) -> float | None:
    try:
        v = row.get("DATA_VALUE", "")
        return float(str(v).replace(",", "")) if v else None
    except Exception:
        return None


def _top10_with_yoy(by_date: dict) -> list[dict]:
    """최신 월 기준 상위 10개국 + 전년 동월 대비."""
    dates = sorted(by_date.keys())
    if not dates:
        return []
    latest_date = dates[-1]
    prev_year   = f"{int(latest_date[:4]) - 1}{latest_date[4:]}"
    prev        = by_date.get(prev_year, {})

    top = sorted(by_date[latest_date].items(), key=lambda x: -x[1]["value"])[:10]
    total = sum(info["value"] for _, info in top)

    result = []
    for code, info in top:
        item: dict = {
            "code":      code,
            "name":      info["name"],
            "value":     info["value"],
            "date":      latest_date,
            "share_pct": round(info["value"] / total * 100, 1) if total else None,
        }
        if code in prev and prev[code]["value"]:
            cur, prv = info["value"], prev[code]["value"]
            item["yoy"] = round((cur - prv) / abs(prv) * 100, 1)
        result.append(item)
    return result


def _country_trend(by_date: dict, key_countries: list[str], n: int = 12) -> list[dict]:
    """주요국 최근 n개월 추이."""
    dates = sorted(by_date.keys())[-n:]
    result = []
    for d in dates:
        entry: dict = {"date": d}
        month_data = by_date.get(d, {})
        for code in key_countries:
            if code in month_data:
                entry[code] = month_data[code]["value"]
        result.append(entry)
    return result


# ── 관세청 API ───────────────────────────────────────────────────────

# HS 코드 → 섹터 매핑 (4자리 prefix, 관세청 품목별수출입통계)
_CUSTOMS_EXP_HS = [
    {"id": "semiconductor", "hs": ["8541", "8542"]},
    {"id": "auto",          "hs": ["8703", "8704"]},
    {"id": "petroleum",     "hs": ["2710"]},
    {"id": "ship",          "hs": ["8901"]},
    {"id": "battery",       "hs": ["8507"]},
    {"id": "display",       "hs": ["8524"]},
    {"id": "wireless",      "hs": ["8517"]},
    # 석유화학·기계는 HS 범위 복잡 → BOK 추정값 유지
    {"id": "petrochem",     "hs": []},
    {"id": "machinery",     "hs": []},
    {"id": "steel",         "hs": []},
]

_CUSTOMS_IMP_HS = [
    {"id": "oil",       "hs": ["2709"]},
    {"id": "semi",      "hs": ["8541", "8542"]},
    {"id": "gas",       "hs": ["2711"]},
    {"id": "coal",      "hs": ["2701"]},
    {"id": "computer",  "hs": ["8471"]},
    {"id": "auto",      "hs": ["8703"]},
    # 기계류·석유화학·농산물 → BOK 추정값 유지
    {"id": "machinery", "hs": []},
    {"id": "petrochem", "hs": []},
    {"id": "metals",    "hs": []},
    {"id": "agri",      "hs": []},
]


def _customs_val(hs: str, yyyymm: str) -> tuple[float, float]:
    """관세청 품목별수출입 API: HS 4자리 prefix × 월 → (수출USD, 수입USD)."""
    try:
        r = requests.get(
            CUSTOMS_BASE,
            params={
                "serviceKey": CUSTOMS_KEY,
                "strtYymm": yyyymm,
                "endYymm":   yyyymm,
                "hsSgn":     hs,
                "pageNo":    "1",
                "numOfRows": "1",
            },
            timeout=12,
        )
        root = ET.fromstring(r.text)
        if root.findtext(".//resultCode") != "00":
            return 0.0, 0.0
        items = root.findall(".//item")
        if not items:
            return 0.0, 0.0
        d = {c.tag: c.text for c in items[0]}
        if d.get("hsCd") != "-":   # 집계 행이 아님
            return 0.0, 0.0
        return float(d.get("expDlr") or 0), float(d.get("impDlr") or 0)
    except Exception as e:
        logger.debug(f"[customs] {hs}/{yyyymm}: {e}")
        return 0.0, 0.0


def _find_latest_customs_month() -> str | None:
    """최신 관세청 데이터 월 탐색. 관세청 데이터는 보통 1~2개월 지연."""
    now = datetime.now()
    for i in range(1, 7):   # 1개월 전부터 시작 (당월은 미게시)
        m  = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        ym = m.strftime("%Y%m")
        exp, _ = _customs_val("8542", ym)
        if exp > 0:
            return ym
    return None


def _fetch_customs_sectors(
    exports_mn: float | None,
    imports_mn: float | None,
) -> dict | None:
    """관세청 API로 실제 섹터별 수출입 수집. HS 매핑 없는 섹터는 BOK 추정 유지."""
    if not CUSTOMS_KEY:
        return None

    latest_ym = _find_latest_customs_month()
    if not latest_ym:
        return None

    prev_ym = f"{int(latest_ym[:4]) - 1}{latest_ym[4:]}"

    # 모든 고유 (hs, ym) 쌍 수집
    hs_pairs: set[tuple[str, str]] = set()
    for s in _CUSTOMS_EXP_HS + _CUSTOMS_IMP_HS:
        for hs in s["hs"]:
            hs_pairs.add((hs, latest_ym))
            hs_pairs.add((hs, prev_ym))

    # 병렬 조회
    vals: dict[tuple[str, str], tuple[float, float]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        future_map = {ex.submit(_customs_val, hs, ym): (hs, ym) for hs, ym in hs_pairs}
        for fut in concurrent.futures.as_completed(future_map):
            key = future_map[fut]
            vals[key] = fut.result()

    def _sector_val(hs_list: list, ym: str) -> tuple[float, float]:
        exp_tot = imp_tot = 0.0
        for hs in hs_list:
            e, i = vals.get((hs, ym), (0.0, 0.0))
            exp_tot += e
            imp_tot += i
        return exp_tot, imp_tot

    def _build_list(sectors_hs: list, base_sectors: list, use_exp: bool, total_mn: float | None) -> list[dict]:
        base_map = {s["id"]: s for s in base_sectors}
        out = []
        for s in sectors_hs:
            hs = s["id"]
            entry: dict = {
                "id":   hs,
                "name": base_map[hs]["name"],
                "share2024": base_map[hs]["share"],
            }
            hs_list = s["hs"]
            if hs_list:
                ec, ic = _sector_val(hs_list, latest_ym)
                ep, ip = _sector_val(hs_list, prev_ym)
                raw_cur  = ec if use_exp else ic
                raw_prev = ep if use_exp else ip
                entry["value_mn_usd"] = round(raw_cur / 1_000_000)
                if raw_prev > 0:
                    entry["yoy"] = round((raw_cur - raw_prev) / raw_prev * 100, 1)
                entry["real"] = True
            else:
                # BOK 추정값
                if total_mn is not None:
                    entry["value_mn_usd"] = round(total_mn * base_map[hs]["share"] / 100)
                entry["real"] = False
            out.append(entry)
        return out

    exp_list = sorted(_build_list(_CUSTOMS_EXP_HS, _EXPORT_SECTORS, True,  exports_mn), key=lambda x: -(x.get("value_mn_usd") or 0))
    imp_list = sorted(_build_list(_CUSTOMS_IMP_HS, _IMPORT_SECTORS, False, imports_mn), key=lambda x: -(x.get("value_mn_usd") or 0))

    return {
        "exports":    exp_list,
        "imports":    imp_list,
        "latest_ym":  latest_ym,
        "note": (
            f"실제(관세청 {latest_ym}) | "
            "추정: BOK 총액 × KITA/MOTIE 2024 비중"
        ),
    }


# ── 섹터 정의 (2024년 KITA/MOTIE 공식 발표 비중) ─────────────────────

_EXPORT_SECTORS = [
    {"id": "semiconductor", "name": "반도체",       "bok": "209AA", "share": 20.4},
    {"id": "auto",          "name": "자동차·부품",  "bok": "202AA", "share": 16.3},
    {"id": "petrochem",     "name": "석유화학",     "bok": "205AA", "share": 7.3},
    {"id": "machinery",     "name": "일반기계",     "bok": "203AA", "share": 7.4},
    {"id": "petroleum",     "name": "석유제품",     "bok": "205AA", "share": 7.0},
    {"id": "steel",         "name": "철강제품",     "bok": None,    "share": 5.1},
    {"id": "ship",          "name": "선박",         "bok": "203AA", "share": 3.8},
    {"id": "battery",       "name": "이차전지",     "bok": "209AA", "share": 3.1},
    {"id": "display",       "name": "디스플레이",   "bok": "209AA", "share": 2.7},
    {"id": "wireless",      "name": "무선통신기기", "bok": "209AA", "share": 2.7},
]

_IMPORT_SECTORS = [
    {"id": "oil",       "name": "원유",     "share": 14.5},
    {"id": "semi",      "name": "반도체",   "share": 10.8},
    {"id": "gas",       "name": "천연가스", "share": 8.5},
    {"id": "machinery", "name": "기계류",   "share": 7.6},
    {"id": "petrochem", "name": "석유화학", "share": 5.8},
    {"id": "coal",      "name": "석탄",     "share": 4.5},
    {"id": "metals",    "name": "철강·금속","share": 4.1},
    {"id": "computer",  "name": "컴퓨터",   "share": 3.2},
    {"id": "auto",      "name": "자동차",   "share": 2.8},
    {"id": "agri",      "name": "농산물",   "share": 2.5},
]


def _fetch_price_yoy(bok_code: str) -> float | None:
    """BOK 402Y015 수출물가지수 — 섹터별 YoY 변동률(%)."""
    if not BOK_KEY or not bok_code:
        return None
    try:
        now = datetime.now()
        start = now.replace(year=now.year - 3).strftime("%Y%m")
        end   = now.strftime("%Y%m")
        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_KEY}/json/kr/"
            f"1/40/402Y015/M/{start}/{end}/{bok_code}"
        )
        rows = requests.get(url, timeout=10).json().get("StatisticSearch", {}).get("row", [])
        series = sorted(
            (r["TIME"], float(r["DATA_VALUE"]))
            for r in rows if r.get("TIME") and r.get("DATA_VALUE")
        )
        if not series:
            return None
        latest_t, latest_v = series[-1]
        prev_t = f"{int(latest_t[:4]) - 1}{latest_t[4:]}"
        prev = [(t, v) for t, v in series if t == prev_t]
        if not prev:
            return None
        return round((latest_v - prev[0][1]) / abs(prev[0][1]) * 100, 1)
    except Exception as e:
        logger.debug(f"[trade] 402Y015/{bok_code}: {e}")
        return None


def _build_sectors(exports_mn: float | None, imports_mn: float | None) -> dict:
    """섹터별 수출입 현황.

    value_mn_usd: BOK 월 총액 × 2024년 KITA/MOTIE 공식 비중 (추정)
    price_yoy   : BOK 402Y015 수출물가지수 YoY (실제, 최신 약 6~12개월 지연)
    """
    # 섹터별 가격지수 YoY 수집 (중복 BOK 코드 방지)
    fetched: dict[str, float | None] = {}
    for s in _EXPORT_SECTORS:
        code = s["bok"]
        if code and code not in fetched:
            fetched[code] = _fetch_price_yoy(code)

    exp_sectors = []
    for s in _EXPORT_SECTORS:
        entry: dict = {"id": s["id"], "name": s["name"], "share2024": s["share"]}
        if exports_mn is not None:
            entry["value_mn_usd"] = round(exports_mn * s["share"] / 100)
        if s["bok"]:
            entry["price_yoy"] = fetched.get(s["bok"])
        exp_sectors.append(entry)

    imp_sectors = []
    for s in _IMPORT_SECTORS:
        entry = {"id": s["id"], "name": s["name"], "share2024": s["share"]}
        if imports_mn is not None:
            entry["value_mn_usd"] = round(imports_mn * s["share"] / 100)
        imp_sectors.append(entry)

    return {
        "exports": exp_sectors,
        "imports": imp_sectors,
        "note": "추정값: BOK 301Y013 월 총액 × 2024년 KITA/MOTIE 공식 비중 | price_yoy: BOK 402Y015 수출물가지수 YoY",
    }


# ── 데이터 수집 ───────────────────────────────────────────────────────

def _build() -> dict:
    """BOK ECOS에서 수출입 데이터 수집.

    통계표:
      301Y013 — 경상수지 (월별, 단위: 백만달러)
        110000: 상품수출  120000: 상품수입  100000: 상품수지  000000: 경상수지
      901Y121 — 국가별 수출입 (월별, 단위: 천달러)
        T002=수출금액  T004=수입금액  ITEM_CODE2=국가코드
    """
    # ── 월별 종합 추이 (301Y013) ──────────────────────────────────────
    exports_rows = _fetch("301Y013", "110000", "M", 40)
    imports_rows = _fetch("301Y013", "120000", "M", 40)
    balance_rows = _fetch("301Y013", "100000", "M", 40)
    ca_rows      = _fetch("301Y013", "000000", "M",  3)

    date_map: dict[str, dict] = {}
    for key, rows in [("exports", exports_rows), ("imports", imports_rows), ("tradeBalance", balance_rows)]:
        for row in rows:
            d = row.get("TIME", "")
            if d:
                date_map.setdefault(d, {})[key] = _to_float(row)

    series = [{"date": d, **v} for d, v in sorted(date_map.items())]

    latest: dict = {}
    if series:
        latest = dict(series[-1])
        if ca_rows:
            latest["currentAccount"] = _to_float(ca_rows[-1])
        if len(series) >= 13:
            prev = series[-13]
            yoy: dict = {}
            for k in ("exports", "imports", "tradeBalance"):
                cur_v, prv_v = latest.get(k), prev.get(k)
                if cur_v is not None and prv_v:
                    yoy[k] = round((cur_v - prv_v) / abs(prv_v) * 100, 1)
            if yoy:
                latest["yoy"] = yoy
        # MoM
        if len(series) >= 2:
            prev_m = series[-2]
            mom: dict = {}
            for k in ("exports", "imports", "tradeBalance"):
                cur_v, prv_v = latest.get(k), prev_m.get(k)
                if cur_v is not None and prv_v:
                    mom[k] = round((cur_v - prv_v) / abs(prv_v) * 100, 1)
            if mom:
                latest["mom"] = mom

    # ── 국가별 수출/수입 (901Y121) ────────────────────────────────────
    exp_by_date = _fetch_country("T002", n_months=14)  # 수출금액
    imp_by_date = _fetch_country("T004", n_months=14)  # 수입금액

    global_exports = _top10_with_yoy(exp_by_date)
    global_imports = _top10_with_yoy(imp_by_date)

    # 주요 수출 대상국 추이
    key_countries = [item["code"] for item in global_exports[:5]]
    exp_dates = sorted(exp_by_date.keys())
    key_country_meta = []
    if exp_dates:
        last_month = exp_by_date[exp_dates[-1]]
        for code in key_countries:
            if code in last_month:
                key_country_meta.append({"code": code, "name": last_month[code]["name"]})

    country_trend = {
        "exports": _country_trend(exp_by_date, key_countries, n=12),
        "imports": _country_trend(imp_by_date, key_countries, n=12),
        "countries": key_country_meta,
    }

    # ── 섹터별 수출입 ─────────────────────────────────────────────────
    exports_mn = latest.get("exports")
    imports_mn = latest.get("imports")

    # 관세청 실제 데이터 우선, 실패 시 BOK 추정값 fallback
    sectors = _fetch_customs_sectors(exports_mn, imports_mn) or _build_sectors(exports_mn, imports_mn)

    # BOK 402Y015 수출물가지수 YoY → 수출 섹터에 추가 (실제/추정 무관)
    if sectors:
        bok_price_cache: dict[str, float | None] = {}
        for s in _EXPORT_SECTORS:
            code = s.get("bok")
            if code and code not in bok_price_cache:
                bok_price_cache[code] = _fetch_price_yoy(code)
        bok_price_by_id = {s["id"]: bok_price_cache.get(s.get("bok")) for s in _EXPORT_SECTORS}
        for entry in sectors.get("exports", []):
            price_yoy = bok_price_by_id.get(entry["id"])
            if price_yoy is not None:
                entry["price_yoy"] = price_yoy

    return {
        "latest":        latest,
        "series":        series,
        "globalExports": global_exports,
        "globalImports": global_imports,
        "countryTrend":  country_trend,
        "sectors":       sectors,
        "bok_key_set":   bool(BOK_KEY),
    }


# ── 라우트 ────────────────────────────────────────────────────────────

@router.get("/trade_stats", dependencies=[Depends(require_login)])
def trade_stats_page(request: Request):
    return render(request, "stock/trade_stats.html")


@router.get("/api/trade/summary")
def api_trade_summary():
    cached = _load_cache()
    if cached:
        return JSONResponse(cached)
    try:
        data = _build()
        if data.get("series"):
            _save_cache(data)
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[trade] API 오류: {e}", exc_info=True)
        return JSONResponse({
            "latest": {}, "series": [],
            "globalExports": [], "globalImports": [],
            "countryTrend": {"exports": [], "imports": [], "countries": []},
            "sectors": {"exports": [], "imports": [], "note": ""},
            "bok_key_set": bool(BOK_KEY),
            "error": "데이터 조회 실패",
        })
