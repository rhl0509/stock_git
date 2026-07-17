"""
kr_finance_client.py — 한국 주식 재무 데이터 클라이언트 (FMP 대체).

데이터 소스:
  pykrx   : PE, PB, ROE (EPS/BPS), EPS YoY
  DART API: 손익계산서·재무상태표·현금흐름표 기반 9개 지표

fmp_client.py 와 동일한 공개 인터페이스 유지:
  get_financial_features()      → dict (13개, TTM)
  get_financial_features_pit()  → dict (PIT 매칭)
  get_quarterly_history()       → list[dict] (연간 이력 최대 4년)
  FINANCIAL_COLS, _FIN_DEFAULTS, PIT_FILING_LAG_DAYS

캐시:
  data/cache/kr_fin/fin_{code}.json     24h
  data/cache/kr_fin/qhist_{code}.json  30d
"""
import os
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
ROOT      = Path(__file__).parent
CACHE_DIR = ROOT / "data" / "cache" / "kr_fin"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# PIT(Point-in-Time) 공시 시점 추정 지연.
# get_quarterly_history 의 period_end 는 실제 사업연도 종료일(12/31)이고,
# 한국 사업보고서 제출 시한은 다음 해 3/31 이므로 +90일.
# ⚠ feature_v2.build_full_matrix_pit 의 재무 매칭도 반드시 이 값을 쓴다 — 한쪽만
# 다르면 실제 공시보다 이른 재무를 보는 look-ahead 누수가 된다. 단일 소스로 유지할 것.
PIT_FILING_LAG_DAYS = 90

DART_KEY             = os.getenv("DART_API_KEY", "")
CACHE_HOURS          = 24
QUARTERLY_CACHE_HOURS = 24 * 30

FINANCIAL_COLS = [
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "current_ratio", "net_profit_margin", "fcf_yield",
    "gross_margin", "op_margin", "asset_turnover", "quick_ratio",
    "eps_growth_yoy", "revenue_growth_yoy",
]
_FIN_DEFAULTS = {c: 0.0 for c in FINANCIAL_COLS}


# ═══════════════════════════════════════════════════════════════════════════
# 캐시
# ═══════════════════════════════════════════════════════════════════════════

def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _load_cache(key: str, max_hours: float = CACHE_HOURS):
    p = _cache_path(key)
    if not p.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    if age.total_seconds() > max_hours * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(key: str, data) -> None:
    try:
        _cache_path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# pykrx: PE, PB, ROE, EPS YoY
# ═══════════════════════════════════════════════════════════════════════════

def _pykrx_fundamentals(code: str, year: int | None = None) -> dict:
    """
    pykrx로 PE, PB, ROE, EPS YoY 조회.
    year=None → 최근 30일 데이터 (TTM).
    year=N    → N년 12월 연말 데이터 (PIT 이력용).
    """
    try:
        from pykrx import stock

        if year is None:
            end   = datetime.now()
            start = end - timedelta(days=30)
        else:
            end   = datetime(year, 12, 31)
            start = datetime(year, 12, 1)

        s = start.strftime("%Y%m%d")
        e = end.strftime("%Y%m%d")
        df = stock.get_market_fundamental(s, e, code)
        if df is None or df.empty:
            return {}

        row = df.iloc[-1]
        eps = float(row.get("EPS", 0) or 0)
        bps = float(row.get("BPS", 0) or 0)
        per = float(row.get("PER", 0) or 0)
        pbr = float(row.get("PBR", 0) or 0)
        roe = round(eps / bps, 4) if bps > 0 else 0.0

        # EPS YoY: 전년 동기 대비
        if year is None:
            prev_e = end   - timedelta(days=335)
            prev_s = start - timedelta(days=395)
        else:
            prev_e = datetime(year - 1, 12, 31)
            prev_s = datetime(year - 1, 12, 1)

        df_prev = stock.get_market_fundamental(
            prev_s.strftime("%Y%m%d"), prev_e.strftime("%Y%m%d"), code
        )
        eps_yoy = 0.0
        if df_prev is not None and not df_prev.empty:
            prev_eps = float(df_prev.iloc[-1].get("EPS", 0) or 0)
            if prev_eps != 0:
                eps_yoy = round((eps - prev_eps) / abs(prev_eps) * 100, 1)

        return {"pe_ratio": per, "pb_ratio": pbr, "roe": roe, "eps_growth_yoy": eps_yoy}

    except Exception as e:
        logger.debug(f"[kr_fin] pykrx {code} year={year}: {e}")
        return {}


def _pykrx_market_cap(code: str, ref_date: datetime | None = None) -> float:
    """pykrx 시가총액 (원). ref_date 이전 5거래일 범위로 조회해 휴장일 대응."""
    try:
        from pykrx import stock
        end   = (ref_date or datetime.now())
        start = end - timedelta(days=7)
        df = stock.get_market_cap(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
        if df is not None and not df.empty:
            return float(df.iloc[-1].get("시가총액", 0) or 0)
    except Exception:
        pass
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# DART 재무제표 API
# ═══════════════════════════════════════════════════════════════════════════

def _corp_code(stock_code: str) -> str | None:
    """종목코드 → DART corp_code."""
    try:
        from .dart_client import _load_corp_map
        return _load_corp_map().get(stock_code)
    except Exception:
        return None


def _fetch_dart_fs(corp_code: str, bsns_year: str, reprt_code: str = "11011") -> list:
    """
    DART fnlttSinglAcntAll 호출. 연결재무제표(CFS) 우선, 실패 시 별도(OFS).
    reprt_code: 11011=사업보고서(연간), 11012=반기, 11013=1분기, 11014=3분기
    """
    if not DART_KEY:
        return []
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    for fs_div in ("CFS", "OFS"):
        try:
            r = requests.get(url, params={
                "crtfc_key": DART_KEY,
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            }, timeout=10)
            d = r.json()
            if d.get("status") == "000" and d.get("list"):
                return d["list"]
        except Exception as e:
            logger.debug(f"[kr_fin] DART {corp_code} {bsns_year} {fs_div}: {e}")
    return []


def _parse_dart(items: list) -> dict:
    """
    DART 재무제표 항목 리스트 → 지표 dict.
    내부 키 _op_cf, _capex 포함 (FCF yield 계산용).
    """
    def _to_float(s) -> float:
        try:
            return float((s or "0").replace(",", "").strip())
        except Exception:
            return 0.0

    # (sj_div, account_id) → (당기, 전기)
    by_id: dict[str, tuple[float, float]] = {}
    # (sj_div, account_nm 공백제거) → (당기, 전기)
    by_nm: dict[str, tuple[float, float]] = {}

    for it in items:
        sj   = it.get("sj_div", "")
        aid  = it.get("account_id", "")
        nm   = it.get("account_nm", "").replace(" ", "").replace("​", "")
        curr = _to_float(it.get("thstrm_amount"))
        prev = _to_float(it.get("frmtrm_amount"))
        if aid:
            by_id[f"{sj}:{aid}"] = (curr, prev)
        if nm:
            by_nm.setdefault(f"{sj}:{nm}", (curr, prev))

    def lookup(sj: str, aids: list[str], nms: list[str]) -> tuple[float | None, float | None]:
        for aid in aids:
            v = by_id.get(f"{sj}:{aid}")
            if v is not None:
                return v
        for nm in nms:
            v = by_nm.get(f"{sj}:{nm}")
            if v is not None:
                return v
        # 부분 일치 (계정명이 조금씩 다른 경우)
        for nm_kw in nms:
            for k, v in by_nm.items():
                if k.startswith(f"{sj}:") and nm_kw in k[len(sj) + 1:]:
                    return v
        return None, None

    # ── 손익계산서(IS) ─────────────────────────────────────────────────────
    rev, prev_rev = lookup("IS",
        ["ifrs-full_Revenue", "dart_Revenue"],
        ["수익(매출액)", "매출액", "영업수익", "매출"])

    cogs, _ = lookup("IS",
        ["ifrs-full_CostOfSales"],
        ["매출원가"])

    gross, _ = lookup("IS",
        ["ifrs-full_GrossProfit"],
        ["매출총이익", "매출총이익(손실)"])
    if gross is None and rev is not None and cogs is not None:
        gross = rev - cogs

    op_inc, _ = lookup("IS",
        ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
        ["영업이익", "영업이익(손실)"])

    net_inc, _ = lookup("IS",
        ["ifrs-full_ProfitLoss",
         "ifrs-full_ProfitLossAttributableToOwnersOfParent"],
        ["당기순이익", "당기순이익(손실)",
         "지배기업소유주에귀속되는당기순이익"])

    # ── 재무상태표(BS) ─────────────────────────────────────────────────────
    t_assets, _ = lookup("BS",
        ["ifrs-full_Assets"],
        ["자산총계"])

    cur_assets, _ = lookup("BS",
        ["ifrs-full_CurrentAssets"],
        ["유동자산"])

    inventories, _ = lookup("BS",
        ["ifrs-full_Inventories"],
        ["재고자산"])

    cur_liab, _ = lookup("BS",
        ["ifrs-full_CurrentLiabilities"],
        ["유동부채"])

    t_liab, _ = lookup("BS",
        ["ifrs-full_Liabilities"],
        ["부채총계"])

    t_equity, _ = lookup("BS",
        ["ifrs-full_Equity"],
        ["자본총계"])

    # ── 현금흐름표(CF) ─────────────────────────────────────────────────────
    op_cf, _ = lookup("CF",
        ["ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "ifrs-full_CashFlowsFromOperatingActivities"],
        ["영업활동현금흐름", "영업활동으로인한현금흐름"])

    capex, _ = lookup("CF",
        ["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
         "ifrs-full_AcquisitionOfPropertyPlantAndEquipment"],
        ["유형자산의취득", "유형자산취득", "유형자산의취득에따른현금유출"])

    # ── 지표 계산 ──────────────────────────────────────────────────────────
    rv  = rev or 0.0
    out: dict = {}

    out["net_profit_margin"]  = round((net_inc or 0) / rv * 100, 2) if rv else 0.0
    out["gross_margin"]       = round((gross   or 0) / rv * 100, 2) if rv else 0.0
    out["op_margin"]          = round((op_inc  or 0) / rv * 100, 2) if rv else 0.0
    out["asset_turnover"]     = round(rv / t_assets, 4) if t_assets else 0.0
    out["revenue_growth_yoy"] = (
        round((rv - prev_rev) / abs(prev_rev) * 100, 1)
        if prev_rev and prev_rev != 0 else 0.0
    )
    out["debt_to_equity"] = round((t_liab or 0) / t_equity, 3) if t_equity else 0.0
    out["current_ratio"]  = round((cur_assets or 0) / cur_liab, 3) if cur_liab else 0.0
    out["quick_ratio"]    = (
        round(((cur_assets or 0) - (inventories or 0)) / cur_liab, 3)
        if cur_liab else 0.0
    )

    # FCF = 영업CF - CapEx (시총은 별도 주입)
    out["_op_cf"]  = op_cf or 0.0
    out["_capex"]  = abs(capex) if capex is not None else 0.0

    return out


# ═══════════════════════════════════════════════════════════════════════════
# 합산 & FCF yield
# ═══════════════════════════════════════════════════════════════════════════

def _merge(code: str, pykrx_d: dict, dart_d: dict,
           mktcap: float | None = None) -> dict:
    """pykrx + DART 지표 합산. FCF yield 계산 포함."""
    out = dict(_FIN_DEFAULTS)
    out.update(pykrx_d)
    out.update({k: v for k, v in dart_d.items() if not k.startswith("_")})

    op_cf = dart_d.get("_op_cf", 0.0)
    capex = dart_d.get("_capex", 0.0)
    fcf   = op_cf - capex
    if fcf and mktcap is None:
        mktcap = _pykrx_market_cap(code)
    if fcf and mktcap:
        out["fcf_yield"] = round(fcf / mktcap, 4)

    # 음수 비율 클램핑
    out["current_ratio"] = max(0.0, out.get("current_ratio", 0.0))
    out["quick_ratio"]   = max(0.0, out.get("quick_ratio",   0.0))

    return {c: float(out.get(c, 0.0) or 0.0) for c in FINANCIAL_COLS}


# ═══════════════════════════════════════════════════════════════════════════
# 공개 API
# ═══════════════════════════════════════════════════════════════════════════

def get_financial_features(code: str, market: str = "KOSPI") -> dict:
    """
    최신 재무 지표 13개 반환 (TTM).
    캐시 24h. 실패 시 _FIN_DEFAULTS 반환.
    """
    cache_key = f"fin_{code}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    pykrx_d = _pykrx_fundamentals(code)

    dart_d: dict = {}
    cc = _corp_code(code)
    if cc:
        for year_offset in (1, 2):
            year = str(datetime.now().year - year_offset)
            items = _fetch_dart_fs(cc, year, "11011")
            if items:
                dart_d = _parse_dart(items)
                break

    out = _merge(code, pykrx_d, dart_d)
    _save_cache(cache_key, out)
    return out


def get_quarterly_history(code: str, market: str = "KOSPI") -> list[dict]:
    """
    연간 재무 이력 (최대 4년). PIT 학습용.

    period_end = {year}-12-31 (실제 사업연도 종료일):
      → est_filing = period_end + 90d ≈ 다음 해 3/31 (한국 사업보고서 제출 시한)
    반환: [{period_end, pe_ratio, pb_ratio, ..., revenue_growth_yoy}, ...]  (최신순)
    """
    cache_key = f"qhist_{code}"
    cached = _load_cache(cache_key, QUARTERLY_CACHE_HOURS)
    if cached is not None:
        return cached

    cc = _corp_code(code)
    if not cc:
        return []

    current_year = datetime.now().year
    history: list[dict] = []

    for year_offset in range(1, 5):
        year = current_year - year_offset

        # DART 연간 재무제표
        items = _fetch_dart_fs(cc, str(year), "11011")
        if not items:
            time.sleep(0.2)
            continue

        dart_d = _parse_dart(items)

        # pykrx 연말 기준 PE/PB/ROE/EPS YoY
        pykrx_d = _pykrx_fundamentals(code, year=year)

        # 시가총액: 연말 마지막 거래일 기준 (7일 범위로 휴장일 대응)
        mktcap = _pykrx_market_cap(code, ref_date=datetime(year, 12, 31))

        entry = _merge(code, pykrx_d, dart_d, mktcap=mktcap)
        # period_end = 실제 사업연도 종료일(12/31).
        # (과거에 2/15로 두던 방식은 FY(year) 재무가 같은 해 4/1에 공시된 것으로
        #  취급되어 실제 공시(다음 해 3월 말)보다 ~1년 앞선 look-ahead 누수 발생)
        # 공시 가능 시점 추정은 PIT 매칭 쪽에서 period_end + 90d(≈다음 해 3/31)로 계산.
        entry["period_end"] = f"{year}-12-31"
        history.append(entry)

        time.sleep(0.3)   # DART rate limit 완화

    _save_cache(cache_key, history)
    return history


def get_financial_features_pit(code: str, market: str = "KOSPI",
                                as_of_date=None) -> dict:
    """
    PIT(Point-in-Time) 재무 피처.
    as_of_date 기준으로 공시 가능했던 가장 최신 연간 데이터 반환.
    """
    if as_of_date is None:
        return get_financial_features(code, market)

    history = get_quarterly_history(code, market)
    if not history:
        return get_financial_features(code, market)

    import pandas as _pd
    cutoff = _pd.Timestamp(as_of_date)
    best = None
    for q in sorted(history, key=lambda x: x.get("period_end", "")):
        try:
            # 사업연도 종료(12/31) + 90d ≈ 다음 해 3/31 사업보고서 제출 시한
            est = _pd.Timestamp(q["period_end"]) + _pd.Timedelta(days=PIT_FILING_LAG_DAYS)
        except Exception:
            continue
        if est <= cutoff:
            best = q

    if best is None:
        return dict(_FIN_DEFAULTS)

    return {col: float(best.get(col, 0.0) or 0.0) for col in FINANCIAL_COLS}


if __name__ == "__main__":
    import pprint
    print("=== TTM (삼성전자) ===")
    pprint.pprint(get_financial_features("005930"))
    print("\n=== PIT 이력 ===")
    hist = get_quarterly_history("005930")
    for h in hist:
        print(h.get("period_end"), {k: h[k] for k in ["pe_ratio", "op_margin", "roe"]})
