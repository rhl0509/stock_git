"""
XGBoost_v2/daily_recommend.py
==============================
일일 종목 추천 파이프라인 — 앙상블 모델(XGB+LGB+메타) 실제 적용 버전.

동작:
  1. FDR에서 유니버스(시총 상위 N개) 로드
  2. 로컬 수집 OHLCV가 있는 종목에 대해 앙상블 모델 예측 → 신뢰도
  3. OHLCV 없는 종목은 팩터 점수(모멘텀·수급·유동성) 폴백
  4. 신뢰도 × ATR 기반 진입가/목표가/손절가 산출
  5. daily_recommend.json 저장

실행:
  python -m XGBoost_v2.daily_recommend
  python -m XGBoost_v2.daily_recommend --top 15 --min-conf 0.55
"""
from __future__ import annotations

import json, logging, pickle, time
import threading
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .quant_gate import compute_composite_signal

logger = logging.getLogger(__name__)

# 공유 Booster(xgb/lgb/cat)의 .predict 는 스레드 안전성이 보장되지 않는다(버전별 —
# 확인 필요). _model_score_universe 가 ThreadPoolExecutor(8)로, signal.predict 가
# FastAPI 스레드풀로 같은 앙상블에 동시 진입하므로, 추론을 이 락으로 직렬화한다.
# (예측이 CPU 연산이라 직렬화 손실은 작고, I/O 병목은 스레드가 이미 흡수한다.)
_ensemble_predict_lock = threading.Lock()

ROOT       = Path(__file__).parent.parent
MODEL_DIR  = Path(__file__).parent / 'model'
HISTORY_DIR = MODEL_DIR / 'recommend_history'
HISTORY_DIR_ABS = MODEL_DIR / 'recommend_history_abs'
OUTPUT_JSON = MODEL_DIR / 'daily_recommend.json'

MIN_MARCAP   = 100_000_000_000   # 1000억
UNIVERSE_SIZE = 200


def _ensure_dirs() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR_ABS.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────
# 앙상블 모델 로드
# ─────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_ensemble() -> dict | None:
    """
    XGBoost + LightGBM + 메타 모델 로드.
    반환: {label: {xgb, lgb(Optional), meta, has_lgb}, scaler, features}
    모델 파일이 없으면 None 반환.
    """
    scaler_path   = MODEL_DIR / 'scaler_v2.pkl'
    feat_path     = MODEL_DIR / 'feature_list_v2.json'
    if not scaler_path.exists() or not feat_path.exists():
        return None

    try:
        import xgboost as xgb
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        with open(feat_path,   'r', encoding='utf-8') as f:
            features = json.load(f)

        ensemble = {"scaler": scaler, "features": features, "labels": {}}

        for label in ("daily", "short", "swing"):
            xgb_path  = MODEL_DIR / f'xgb_v2_{label}.json'
            meta_path = MODEL_DIR / f'meta_v2_{label}.pkl'
            if not xgb_path.exists():
                continue

            booster = xgb.Booster()
            booster.load_model(str(xgb_path))

            lgb_model = None
            try:
                import lightgbm as lgb
                lgb_path = MODEL_DIR / f'lgb_v2_{label}.txt'
                if lgb_path.exists():
                    lgb_model = lgb.Booster(model_file=str(lgb_path))
            except Exception:
                pass

            cat_model = None
            try:
                from catboost import CatBoostClassifier
                cat_path = MODEL_DIR / f'cat_v2_{label}.cbm'
                if cat_path.exists():
                    cat_model = CatBoostClassifier()
                    cat_model.load_model(str(cat_path))
            except Exception:
                pass

            meta_obj = None
            if meta_path.exists():
                with open(meta_path, 'rb') as f:
                    meta_obj = pickle.load(f)

            ensemble["labels"][label] = {
                "xgb":     booster,
                "lgb":     lgb_model,
                "cat":     cat_model,
                "meta":    meta_obj,
                "has_lgb": lgb_model is not None,
                "has_cat": cat_model is not None,
            }

        if not ensemble["labels"]:
            return None
        return ensemble
    except Exception as e:
        logger.warning(f"[daily] 모델 로드 실패: {e}")
        return None


def reload_ensemble() -> None:
    """lru_cache 초기화 — 재학습 후 모델 파일이 교체되면 호출."""
    _load_ensemble.cache_clear()


def _predict_ensemble(ensemble: dict, X_scaled: np.ndarray,
                      label: str) -> np.ndarray:
    """
    앙상블 예측 확률 반환 (shape: n_samples,).
    학습 시 사용된 모델(has_lgb/has_cat)만 meta 입력에 포함해
    meta 모델의 입력 차원을 맞춤.
    """
    import xgboost as xgb
    lbl   = ensemble["labels"][label]
    meta  = lbl.get("meta") or {}

    # 공유 Booster 동시 호출을 직렬화한다(모듈 헤더 참고). signal.predict 와
    # _model_score_universe(ThreadPool 8) 두 진입점이 같은 객체를 쓴다.
    with _ensemble_predict_lock:
        dmat  = xgb.DMatrix(X_scaled)
        p_xgb = lbl["xgb"].predict(dmat)

        meta_cols = [p_xgb]
        if meta.get("has_lgb") and lbl.get("lgb") is not None:
            meta_cols.append(lbl["lgb"].predict(X_scaled))
        if meta.get("has_cat") and lbl.get("cat") is not None:
            meta_cols.append(lbl["cat"].predict_proba(X_scaled)[:, 1])

        meta_X = (np.column_stack(meta_cols) if len(meta_cols) > 1
                  else meta_cols[0].reshape(-1, 1))

        if meta.get("model") is not None:
            raw_proba = meta["model"].predict_proba(meta_X)[:, 1]
            calibrator = meta.get("calibrator")
            if calibrator is not None:
                return calibrator.predict(raw_proba).astype(np.float32)
            return raw_proba
        return p_xgb


# ─────────────────────────────────────────────────────────────────────────
# ATR 기반 진입가/목표가/손절가
# ─────────────────────────────────────────────────────────────────────────

_ATR_MULT = {
    "daily": {"stop": 1.5, "target": 3.0},
    "short": {"stop": 2.0, "target": 4.0},
    "swing": {"stop": 3.0, "target": 5.0},
}


def _atr_levels(df: pd.DataFrame, price: int,
                category: str) -> tuple[int, int, int]:
    """
    ATR(14) 기반 진입/목표/손절 계산.
    반환: (entry, target, stop) 정수 원화
    """
    try:
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
    except Exception:
        atr = price * 0.02   # 기본값 2%

    mult  = _ATR_MULT.get(category, {"stop": 2.0, "target": 3.0})
    entry  = int(price * 0.997)
    stop   = int(price - mult["stop"]  * atr)
    target = int(price + mult["target"] * atr)
    return entry, target, stop


# ─────────────────────────────────────────────────────────────────────────
# 날짜 헬퍼
# ─────────────────────────────────────────────────────────────────────────

def _last_biz_day() -> str:
    today = datetime.now()
    for back in range(7):
        d = today - timedelta(days=back)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return today.strftime("%Y%m%d")


def _find_working_date(data, max_back: int = 10) -> Optional[str]:
    base = datetime.now()
    for back in range(max_back):
        d = base - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            df = data.krx.ohlcv_one('005930', ds)
            if df is not None and not df.empty and '종가' in df.columns:
                return ds
        except Exception:
            time.sleep(0.3)
    return None


# ─────────────────────────────────────────────────────────────────────────
# 유니버스 빌드 (FDR)
# ─────────────────────────────────────────────────────────────────────────

def _build_universe(data=None, top_n: int = UNIVERSE_SIZE) -> pd.DataFrame:
    """필터 유니버스(100종목) 우선 사용, 실패 시 FDR 폴백."""
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from routes.stock_filter import UNIVERSE as _FILTER_UNIVERSE, KOSDAQ_CODES
        rows = []
        for s in _FILTER_UNIVERSE:
            market = "KOSDAQ" if s["code"] in KOSDAQ_CODES else "KOSPI"
            rows.append({"Code": s["code"], "Name": s["name"],
                         "Market": market, "Marcap": 0})
        logger.info(f"[run_daily] 필터 유니버스 사용: {len(rows)}개")
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"[run_daily] 필터 유니버스 로드 실패({e}), FDR 폴백")

    if data is None:
        return pd.DataFrame()
    listing    = data.fdr.listing('KRX')
    marcap_col = next((c for c in ['Marcap','MarketCap','marcap']
                       if c in listing.columns), None)
    if not marcap_col:
        return pd.DataFrame()
    df = listing.dropna(subset=[marcap_col]).copy()
    df = df[df[marcap_col] >= MIN_MARCAP]
    if 'Market' in df.columns:
        df = df[df['Market'].isin(['KOSPI','KOSDAQ'])]
    if 'Name' in df.columns:
        df = df[~df['Name'].str.contains(
            '스팩|SPAC|KODEX|TIGER|KBSTAR|ARIRANG|KINDEX|HANARO|SOL ',
            regex=True, na=False)]
    df = df.nlargest(top_n, marcap_col).reset_index(drop=True)
    df = df.rename(columns={marcap_col: 'Marcap'})
    keep = [c for c in ['Code','Name','Market','Marcap'] if c in df.columns]
    return df[keep]


# ─────────────────────────────────────────────────────────────────────────
# 모델 예측 기반 추천 (메인 경로)
# ─────────────────────────────────────────────────────────────────────────

def _model_score_universe(universe: pd.DataFrame,
                          ensemble: dict) -> pd.DataFrame:
    """
    로컬 OHLCV가 있는 종목에 대해 앙상블 모델로 신뢰도 예측.
    ThreadPoolExecutor로 병렬 처리 (FMP/DART/뉴스 API 병목 해소).
    """
    from .collect_v2  import load_ohlcv
    from .feature_v2  import (build_technical, build_static_features,
                               build_full_matrix, get_macro,
                               get_market_ohlcv, FULL_COLS)

    scaler    = ensemble["scaler"]
    features  = ensemble["features"]
    macro     = get_macro()
    market_df = get_market_ohlcv()
    total     = len(universe)
    t0        = time.time()

    # FMP 캐시 상태 사전 확인 (cold start 여부 경고)
    fmp_cache_dir = Path(__file__).parent / "data" / "cache" / "fmp"
    fmp_warm = sum(1 for _, r in universe.iterrows()
                   if (fmp_cache_dir / f"fin_{r['Code']}.json").exists()
                   or (fmp_cache_dir / f"keymetrics_{r['Code']}.json").exists())
    ohlcv_dir = Path(__file__).parent / "data" / "ohlcv"
    ohlcv_count = sum(1 for _, r in universe.iterrows()
                      if (ohlcv_dir / f"{r['Code']}.parquet").exists())
    logger.info(f"[run_daily] OHLCV: {ohlcv_count}/{total} | FMP 캐시: {fmp_warm}/{total}"
                + (" (cold start — 첫 실행 느림)" if fmp_warm < total // 2 else ""))

    def _score_one(row):
        code   = row["Code"]
        name   = row.get("Name",   code)
        market = row.get("Market", "KOSPI")
        empty  = {"Code": code, "model_conf_daily": None, "model_conf_short": None,
                  "model_conf_swing": None, "has_model": False, "price": None,
                  "ohlcv": None, "quant_composite": None}

        ohlcv = load_ohlcv(code)
        if ohlcv is None or len(ohlcv) < 80:
            return empty

        try:
            tech    = build_technical(ohlcv, market_df)
            static  = build_static_features(code, name, market)
            X_df    = build_full_matrix(tech, static, macro)

            for col in features:
                if col not in X_df.columns:
                    X_df[col] = 0.0
            X_latest = X_df[features].iloc[-1:].values.astype(np.float32)
            if np.any(~np.isfinite(X_latest)):
                X_latest = np.nan_to_num(X_latest, nan=0.0, posinf=0.0, neginf=0.0)

            X_scaled = scaler.transform(X_latest)
            price    = int(ohlcv["close"].iloc[-1])

            confs = {}
            for label in ("daily", "short", "swing"):
                if label in ensemble["labels"]:
                    confs[label] = float(_predict_ensemble(ensemble, X_scaled, label)[0])
                else:
                    confs[label] = 0.0

            return {"Code": code,
                    "model_conf_daily": confs["daily"],
                    "model_conf_short": confs["short"],
                    "model_conf_swing": confs["swing"],
                    "has_model": True, "price": price, "ohlcv": ohlcv,
                    "quant_composite": compute_composite_signal(ohlcv)}
        except Exception as e:
            logger.debug(f"[daily] {code} 모델 예측 실패: {e}")
            return empty

    rows_input = [row for _, row in universe.iterrows()]
    conf_rows  = [None] * total
    done       = 0
    model_done = 0

    # I/O 병목(FMP/DART/뉴스 API)은 스레드로 병렬화, CPU 연산(XGB predict)은 GIL 영향 최소
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_map = {ex.submit(_score_one, row): i for i, row in enumerate(rows_input)}
        for fut in as_completed(fut_map):
            result = fut.result()
            conf_rows[fut_map[fut]] = result
            done += 1
            if result.get("has_model"):
                model_done += 1
            if done % 10 == 0 or done == total:
                elapsed = time.time() - t0
                logger.info(f"[run_daily] 예측 진행: {done}/{total} | 모델적용: {model_done} ({elapsed:.0f}s)")

    conf_df = pd.DataFrame(conf_rows).set_index("Code")
    return universe.join(conf_df, on="Code")


# ─────────────────────────────────────────────────────────────────────────
# 팩터 점수 (폴백 & 보조 지표)
# ─────────────────────────────────────────────────────────────────────────

def _attach_factor_scores(universe: pd.DataFrame, data,
                          start_3mo: str, start_5d: str,
                          end: str,
                          eps_map: pd.Series | None = None) -> pd.DataFrame:
    """모멘텀·수급·유동성·EPS 팩터 점수 부착 (FDR/KRX 기반)."""
    def _fdr_date(s): return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    s3_fdr = _fdr_date(start_3mo)
    e_fdr  = _fdr_date(end)

    rows, flow_fail, flow_att = [], 0, 0
    for _, row in universe.iterrows():
        code = row["Code"]
        name = row.get("Name", code)
        try:
            ohlcv = data.fdr.price(code, s3_fdr, e_fdr)
            if ohlcv is None or ohlcv.empty or "Close" not in ohlcv.columns:
                continue
            if len(ohlcv) < 2 or float(ohlcv["Close"].iloc[0]) <= 0:
                continue
            momentum  = (float(ohlcv["Close"].iloc[-1]) /
                         float(ohlcv["Close"].iloc[0]) - 1) * 100
            avg_value = (float((ohlcv["Close"].tail(20) *
                                ohlcv["Volume"].tail(20)).mean())
                         if "Volume" in ohlcv.columns else 0.0)
            close_last = float(ohlcv["Close"].iloc[-1])

            flow_total = 0.0
            flow_att  += 1
            try:
                fl = data.krx.investor_flow(code, start_5d, end)
                if fl is not None and not fl.empty:
                    for col in ["외국인합계", "기관합계"]:
                        if col in fl.columns:
                            flow_total += float(fl[col].sum())
            except Exception:
                flow_fail += 1

            eps_val = float((eps_map.get(code, 0) if eps_map is not None else 0) or 0)
            n = len(ohlcv)
            momentum_5d  = (float(ohlcv["Close"].iloc[-1]) / float(ohlcv["Close"].iloc[max(-6,  -n)]) - 1) * 100 if n >= 6  else momentum
            momentum_20d = (float(ohlcv["Close"].iloc[-1]) / float(ohlcv["Close"].iloc[max(-21, -n)]) - 1) * 100 if n >= 21 else momentum
            rows.append({"Code": code, "Name": name,
                         "Market": row.get("Market","KOSPI"),
                         "Marcap": row.get("Marcap", 0),
                         "close": int(close_last),
                         "momentum":     momentum,
                         "momentum_20d": momentum_20d,
                         "momentum_5d":  momentum_5d,
                         "flow": flow_total,
                         "avg_value": avg_value,
                         "eps": eps_val})
            time.sleep(0.05)
        except Exception as e:
            logger.debug(f"  {code} 팩터 실패: {e}")
            time.sleep(0.1)

    if flow_att > 0:
        logger.info(f"  수급: {flow_att-flow_fail}/{flow_att} 성공")
    return pd.DataFrame(rows).set_index("Code") if rows else pd.DataFrame()


def _fetch_eps(date_str: str) -> pd.Series:
    """pykrx로 KOSPI+KOSDAQ 전체 EPS 한 번에 조회. index=종목코드, value=EPS(원)."""
    try:
        from pykrx import stock as pkstock
        dfs = []
        for mkt in ("KOSPI", "KOSDAQ"):
            try:
                df = pkstock.get_market_fundamental(date_str, market=mkt)
                if df is not None and not df.empty and "EPS" in df.columns:
                    dfs.append(df["EPS"])
            except Exception:
                pass
        if dfs:
            return pd.concat(dfs).astype(float)
    except Exception as e:
        logger.warning(f"[daily] EPS 조회 실패: {e}")
    return pd.Series(dtype=float)


def _percentile_rank(s: pd.Series, asc: bool = True) -> pd.Series:
    return s.rank(ascending=asc, pct=True).fillna(0.5)


def _compute_factor_score(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["score_momentum"]  = _percentile_rank(df["momentum"],  asc=False)
    df["score_liquidity"] = _percentile_rank(df["avg_value"], asc=False)

    has_5d  = "momentum_5d"  in df.columns and df["momentum_5d"].abs().sum()  > 0
    has_20d = "momentum_20d" in df.columns and df["momentum_20d"].abs().sum() > 0
    score_mom_5d  = _percentile_rank(df["momentum_5d"],  asc=False) if has_5d  else df["score_momentum"]
    score_mom_20d = _percentile_rank(df["momentum_20d"], asc=False) if has_20d else df["score_momentum"]

    eps_has = "eps" in df.columns and df["eps"].abs().sum() > 0
    if eps_has:
        df["score_eps"] = _percentile_rank(df["eps"].clip(lower=0), asc=False)
    else:
        df["score_eps"] = 0.5

    flow_has = df["flow"].abs().sum() > 0 and (df["flow"] != 0).sum() >= 5
    if flow_has:
        df["score_flow"] = _percentile_rank(df["flow"], asc=False)
    else:
        df["score_flow"] = 0.5

    sf = df["score_flow"]

    # 공통 short 기반 팩터 (기존 로직 유지)
    if flow_has:
        df["factor_score"] = (df["score_momentum"] * 0.40 + sf * 0.30
                            + df["score_liquidity"] * 0.10 + df["score_eps"] * 0.20)
    else:
        df["factor_score"] = (df["score_momentum"] * 0.50
                            + df["score_liquidity"] * 0.20 + df["score_eps"] * 0.30)

    # 당일: 5일 모멘텀(최근 급등) + 거래량(단기 수급)
    df["factor_score_daily"] = (score_mom_5d             * 0.55
                              + df["score_liquidity"]    * 0.30
                              + sf                       * 0.15)

    # 단기: 20일 모멘텀 + 수급 + EPS
    df["factor_score_short"] = (score_mom_20d            * 0.40
                              + sf                       * 0.30
                              + df["score_eps"]          * 0.15
                              + df["score_liquidity"]    * 0.15)

    # 스윙: 90일 모멘텀(추세) + EPS(펀더멘털) + 수급
    df["factor_score_swing"] = (df["score_momentum"]     * 0.30
                              + df["score_eps"]          * 0.30
                              + sf                       * 0.25
                              + df["score_liquidity"]    * 0.15)
    return df


# ─────────────────────────────────────────────────────────────────────────
# 픽 생성
# ─────────────────────────────────────────────────────────────────────────

CATEGORY_TARGET_PCT = {
    "daily": 0.02, "short": 0.03, "swing": 0.07,
}


def _make_pick(row: pd.Series, category: str,
               conf: float, use_atr: bool = True) -> Optional[dict]:
    code  = str(row.get("Code") or row.name)
    price = int(row.get("close", 0))
    if price <= 0:
        return None

    ohlcv = row.get("ohlcv")
    if use_atr and ohlcv is not None:
        entry, target, stop = _atr_levels(ohlcv, price, category)
    else:
        tpct = CATEGORY_TARGET_PCT[category]
        spct = {"daily": 0.03, "short": 0.04, "swing": 0.05}[category]
        entry  = int(price * 0.997)
        target = int(price * (1 + tpct))
        stop   = int(price * (1 - spct))

    expected = (target - price) / price if price else 0.0

    # 순수 모델 점수의 횡단면 퍼센타일 랭크 (0~1, 1=유니버스 최상위).
    # 홀드아웃 검증 결과 edge 는 절대 conf 가 아니라 이 상대 순위에 있다. 참고 지표로 노출.
    mp = row.get(f"model_pct_{category}")
    model_rank_pct = (round(float(mp), 4)
                      if mp is not None and pd.notna(mp) else None)

    return {
        "code":            code,
        "name":            row.get("Name", code),
        "market":          row.get("Market", "KOSPI"),
        "price":           price,
        "entry":           entry,
        "target":          target,
        "stop":            stop,
        "expected_return": round(expected, 4),
        "confidence":      round(conf, 4),
        "model_rank_pct":  model_rank_pct,   # 횡단면 상대순위 (edge 지표) — None=모델 미적용
        "source":          "model" if row.get("has_model") else "factor",
        "eps": int(row.get("eps", 0) or 0),
        "factors": {
            "momentum":  round(float(row.get("score_momentum", 0) or 0), 4),
            "flow":      round(float(row.get("score_flow",     0) or 0), 4),
            "liquidity": round(float(row.get("score_liquidity",0) or 0), 4),
            "eps":       round(float(row.get("score_eps",      0) or 0), 4),
        },
    }


# ─────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────

def run_daily(top: Optional[int] = 15,
              min_conf: float = 0.55,
              universe_size: int = UNIVERSE_SIZE,
              save_txt: bool = False,
              normalize: bool = True) -> dict:

    try:
        from korea_stock_data import KoreaStockData
    except ImportError as e:
        return {"error": f"의존성 누락: {e}"}

    _ensure_dirs()
    logger.info(f"[run_daily] 시작 (min_conf={min_conf}, top={top})")

    try:
        data = KoreaStockData()
    except Exception as e:
        return {"error": f"데이터 수집기 초기화 실패: {e}"}

    end_date = _find_working_date(data)
    if not end_date:
        return {"error": "최근 영업일 KRX 데이터 수신 실패"}

    start_3mo = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
    start_5d  = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
    logger.info(f"[run_daily] 기준일 {end_date}")

    # 1) 앙상블 모델 로드
    ensemble = _load_ensemble()
    if ensemble:
        labels_available = list(ensemble["labels"].keys())
        logger.info(f"[run_daily] 앙상블 모델 로드 완료 (라벨: {labels_available})")
    else:
        logger.warning("[run_daily] 모델 없음 — 팩터 점수만 사용 (run_monthly.bat으로 학습 필요)")

    # 2) 유니버스
    universe = _build_universe(data, top_n=universe_size)
    if universe.empty:
        return {"error": "FDR 종목 리스트 비어있음"}
    logger.info(f"[run_daily] 유니버스 {len(universe)}개")

    # 3) 모델 예측 (OHLCV 있는 종목)
    if ensemble:
        logger.info("[run_daily] 앙상블 모델 예측 중...")
        universe = _model_score_universe(universe, ensemble)
        n_model  = universe.get("has_model", pd.Series(False)).sum()
        logger.info(f"[run_daily] 모델 예측 완료: {n_model}/{len(universe)}개")
    else:
        universe["has_model"]        = False
        universe["model_conf_daily"] = None
        universe["model_conf_short"] = None
        universe["model_conf_swing"] = None
        universe["price"]            = None
        universe["ohlcv"]            = None
        universe["quant_composite"]  = None

    # 4) 팩터 점수 (보조 + 폴백)
    logger.info("[run_daily] EPS 조회 중...")
    eps_map = _fetch_eps(end_date)
    logger.info(f"[run_daily] EPS 조회 완료: {len(eps_map)}개 종목")

    logger.info("[run_daily] 팩터 점수 수집 중...")
    factor_df = _attach_factor_scores(universe, data, start_3mo, start_5d, end_date, eps_map)
    if factor_df.empty:
        return {"error": "팩터 데이터 수집 실패"}
    factor_df = _compute_factor_score(factor_df)

    # universe에 팩터 점수 합류
    extra_cols = ["close","momentum","momentum_20d","momentum_5d","flow","avg_value",
                  "factor_score","factor_score_daily","factor_score_short","factor_score_swing",
                  "score_momentum","score_flow","score_liquidity","eps","score_eps"]
    universe = universe.join(factor_df[[c for c in extra_cols if c in factor_df.columns]],
                              on="Code", rsuffix="_fdr")
    # price 없으면 FDR close 사용
    if "close" in universe.columns and "close_fdr" in universe.columns:
        universe["close"] = universe["close"].combine_first(universe["close_fdr"])

    # 4) 모델 점수 세션 내 정규화 → [0.05, 0.95] 범위로 스케일 (A 페이지 전용)
    if normalize:
        has_model = universe["has_model"].fillna(False).astype(bool)
        for _lbl in ("daily", "short", "swing"):
            col = f"model_conf_{_lbl}"
            if col not in universe.columns:
                continue
            vals = universe.loc[has_model, col].dropna()
            if len(vals) > 1 and (vals.max() - vals.min()) > 1e-6:
                lo, hi = vals.min(), vals.max()
                universe.loc[has_model, col] = (
                    0.05 + 0.90 * (universe.loc[has_model, col] - lo) / (hi - lo)
                )

    # 5) 최종 신뢰도 = 모델(60%) + 카테고리별 팩터(40%) 혼합 (모델 없으면 팩터 100%)
    has_m = universe["has_model"].fillna(False).astype(bool)
    for _lbl in ("daily", "short", "swing"):
        fc_col = f"factor_score_{_lbl}"
        fc_cat = universe[fc_col].fillna(0.5) if fc_col in universe.columns else universe["factor_score"].fillna(0.5)
        mc = universe[f"model_conf_{_lbl}"].fillna(0.0)
        universe[f"conf_{_lbl}"] = np.where(
            has_m & universe[f"model_conf_{_lbl}"].notna(),
            mc * 0.60 + fc_cat * 0.40,
            fc_cat,
        )

    # 5-b) 순수 모델 점수의 횡단면 퍼센타일 랭크 (model_pct_{label}, 0~1, 1=최상위).
    # 검증에서 edge 가 확인된 지표(절대 conf 아닌 상대 순위). 픽에 참고로 노출.
    # rank(pct=True)는 단조변환 불변이라 normalize 전/후 무관. 모델 미적용 종목은 NaN.
    for _lbl in ("daily", "short", "swing"):
        mcol = f"model_conf_{_lbl}"
        pcol = f"model_pct_{_lbl}"
        universe[pcol] = np.nan
        if mcol in universe.columns:
            m_mask = has_m & universe[mcol].notna()
            if m_mask.any():
                universe.loc[m_mask, pcol] = (
                    universe.loc[m_mask, mcol].rank(ascending=True, pct=True))

    # 6) 필터링 & 픽
    size = top if top else 50

    def pick_n(sort_col: str, conf_col: str, category: str) -> list:
        pool = universe[universe[conf_col] >= min_conf].copy()
        if "quant_composite" in pool.columns:
            model_mask = pool["has_model"].fillna(False).astype(bool)
            quant_ok   = pool["quant_composite"].fillna(0) > 0.0
            pool = pool[~model_mask | quant_ok]
        ranked = pool.nlargest(size, sort_col)
        picks  = []
        for _, row in ranked.iterrows():
            p = _make_pick(row, category, float(row[conf_col]),
                           use_atr=bool(row.get("has_model")))
            if p:
                picks.append(p)
        return picks

    daily_picks = pick_n("conf_daily", "conf_daily", "daily")
    short_picks = pick_n("conf_short", "conf_short", "short")
    swing_picks = pick_n("conf_swing", "conf_swing", "swing")
    n_buy = len(daily_picks) + len(short_picks) + len(swing_picks)

    # 6-b) 멀티라벨 강력추천 — 3개 라벨 모두 min_conf 이상인 종목
    universe["combined_score"] = (
        universe["conf_daily"] * 0.30 +
        universe["conf_short"] * 0.40 +
        universe["conf_swing"] * 0.30
    )
    universe["multi_signal"] = (
        (universe["conf_daily"] >= min_conf).astype(int) +
        (universe["conf_short"] >= min_conf).astype(int) +
        (universe["conf_swing"] >= min_conf).astype(int)
    )
    triple_pool = universe[universe["multi_signal"] == 3].copy()
    triple_picks = []
    for _, row in triple_pool.nlargest(5, "combined_score").iterrows():
        p = _make_pick(row, "short", float(row["combined_score"]),
                       use_atr=bool(row.get("has_model")))
        if p:
            p["multi_signal"] = int(row["multi_signal"])
            p["combined_score"] = round(float(row["combined_score"]), 4)
            triple_picks.append(p)

    # 7) 저장
    output = {
        "generated_at":  datetime.now().isoformat(),
        "base_date":     end_date,
        "n_total":       len(universe),
        "n_buy":         n_buy,
        "min_conf":      min_conf,
        "universe_size": len(universe),
        "model_used":    ensemble is not None,
        "triple":        triple_picks,
        "daily":         daily_picks,
        "short":         short_picks,
        "swing":         swing_picks,
    }

    output["normalize"] = normalize

    out_path = OUTPUT_JSON if normalize else MODEL_DIR / 'daily_recommend_abs.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    history_dir = HISTORY_DIR if normalize else HISTORY_DIR_ABS
    history_path = history_dir / f"{datetime.now().strftime('%Y%m%d')}.json"
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if save_txt:
        txt = MODEL_DIR / f"daily_recommend_{datetime.now().strftime('%Y%m%d')}.txt"
        with open(txt, 'w', encoding='utf-8') as f:
            model_tag = "[모델]" if output["model_used"] else "[팩터]"
            for cat, items in [('데일리',daily_picks),('단타',short_picks),('스윙',swing_picks)]:
                f.write(f"\n=== {cat} {model_tag} ({len(items)}종목) ===\n")
                for r in items:
                    f.write(f"{r['name']:10s}({r['code']}) {r['market']:6s} "
                            f"현재 {r['price']:>8,}  목표 {r['target']:>8,}  "
                            f"손절 {r['stop']:>8,}  신뢰도 {r['confidence']:.2f}  "
                            f"출처 {r['source']}\n")

    logger.info(f"[run_daily] 완료 — 추천 {n_buy}개 | 강력추천 {len(triple_picks)}개 | 모델 적용: {output['model_used']}")
    return {"ok": True, "n_buy": n_buy, "n_total": len(universe),
            "model_used": output["model_used"],
            "generated_at": output["generated_at"]}


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--top',      type=int,   default=15)
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--universe', type=int,   default=UNIVERSE_SIZE)
    parser.add_argument('--save-txt', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    result = run_daily(top=args.top, min_conf=args.min_conf,
                       universe_size=args.universe, save_txt=args.save_txt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
