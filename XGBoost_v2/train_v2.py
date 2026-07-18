"""
train_v2.py — 앙상블 모델 학습 (82 피처 + 다중 기간 라벨).

라벨 정의:
  daily_label  : 3일 후 +2% 이상 AND 낙폭 -1.5% 이하
  short_label  : 5일 후 +3% 이상 AND 낙폭 -2% 이하
  swing_label  : 14일 후 +7% 이상 AND 낙폭 -4% 이하

모델 구조 (라벨별):
  1. XGBoost (Focal Loss + 샘플 가중치)
  2. LightGBM (샘플 가중치)
  3. 스태킹 메타-러너: Logistic Regression (XGB + LGB OOF 스택)

저장 파일 (model/):
  xgb_v2_{label}.json        XGBoost booster
  lgb_v2_{label}.txt         LightGBM booster
  meta_v2_{label}.pkl        스태킹 메타 모델
  scaler_v2.pkl              StandardScaler (공용)
  feature_list_v2.json       피처 이름 목록
  label_configs_v2.json      라벨 설정
  shap_importance_v2.json    SHAP 피처 중요도 (XGB 기준)
  train_report_v2.json       학습 보고서

실행:
  python -m XGBoost_v2.train_v2 --train-end 2023-12-31 --source local --skip-optuna
  python -m XGBoost_v2.train_v2 --train-end 2023-12-31 --source local --trials 20
"""
import sys, json, pickle, logging, argparse, warnings
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
# walk_forward_cv / get_oof_predictions 가 폴드마다 fit 하므로 모듈 레벨에 둔다
# (예전에는 main() 안에서만 임포트했다).
from sklearn.preprocessing import StandardScaler

from .collect_v2 import load_ohlcv, list_collected, load_ticker_meta
from .feature_v2 import (
    build_technical, build_static_features, get_macro,
    build_full_matrix, build_full_matrix_pit, FULL_COLS,
    PIT_FILING_LAG_DAYS,
)
from .fmp_client import get_quarterly_history

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent
MODEL_DIR = ROOT / 'model'
MODEL_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 라벨 정의
# ═══════════════════════════════════════════════════════════════════════════

LABEL_CONFIGS = {
    "daily": {"days":  3, "ret":  0.02, "dd": -0.015},
    "short": {"days":  5, "ret":  0.03, "dd": -0.02},
    "swing": {"days": 14, "ret":  0.07, "dd": -0.04},
}


def make_label(df: pd.DataFrame, days: int,
               ret: float, dd: float) -> pd.Series:
    close = df["close"]
    low   = df["low"]

    fwd_close   = close.shift(-days)
    stock_ret   = (fwd_close - close) / close
    low_fwd_min = low.shift(-(days - 1)).rolling(days).min()
    mdd         = (low_fwd_min - close) / close

    labels = ((stock_ret > ret) & (mdd > dd)).astype(float)
    labels.iloc[-days:] = np.nan
    return labels


# ═══════════════════════════════════════════════════════════════════════════
# 샘플 가중치 (최신 데이터 우대)
# ═══════════════════════════════════════════════════════════════════════════

def compute_sample_weights(dates: np.ndarray,
                           half_life_days: int = 180) -> np.ndarray:
    """
    지수 감쇠 가중치: weight = 2^(-days_back / half_life).
    최신 데이터 weight≈1, 180일 전 weight≈0.5.
    """
    if len(dates) == 0:
        return np.ones(0, dtype=np.float32)
    max_ts = np.max(dates)
    days_back = (max_ts - dates) / np.timedelta64(1, 'D')
    weights = np.power(2.0, -days_back / half_life_days).astype(np.float32)
    return weights / weights.mean()   # 평균 1로 정규화


# ═══════════════════════════════════════════════════════════════════════════
# Focal Loss (XGBoost 커스텀 목적함수)
# ═══════════════════════════════════════════════════════════════════════════

def focal_loss_objective(gamma: float = 2.0):
    """
    Focal Loss gradient/hessian for XGBoost.
    불균형 데이터에서 어려운 샘플에 더 큰 페널티 부여.
    """
    def objective(preds, dtrain):
        labels  = dtrain.get_label()
        preds   = 1.0 / (1.0 + np.exp(-preds))
        grad    = preds - labels
        hess    = preds * (1.0 - preds)
        pt      = np.where(labels == 1, preds, 1 - preds)
        focal_w = (1 - pt) ** gamma
        return grad * focal_w, hess * focal_w + 1e-6
    return objective


# ═══════════════════════════════════════════════════════════════════════════
# 데이터 빌드 (PIT 지원)
# ═══════════════════════════════════════════════════════════════════════════

def build_training_data(
    tickers: list[str],
    train_end: pd.Timestamp | None = None,
    use_pit: bool = True,
    market_df: pd.DataFrame | None = None,
) -> tuple[np.ndarray, np.ndarray, dict, list[str], list[str]]:
    """
    여러 종목의 피처 + 3개 라벨 통합 빌드.

    Returns:
        X            : (n, n_features) float32
        dates        : (n,) datetime64  — 샘플 가중치 계산용
        labels_dict  : {"daily": y1, ...}
        feature_names: FULL_COLS
        used_tickers : 실제 사용된 종목 코드
    """
    meta  = load_ticker_meta()
    macro = get_macro()
    logger.info(f"[build] 거시 피처: {macro}")
    logger.info(f"[build] PIT 재무 매칭: {'활성' if use_pit else '비활성'}")

    all_X, all_dates = [], []
    all_labels = {k: [] for k in LABEL_CONFIGS}
    used, skipped = [], 0

    for i, code in enumerate(tickers):
        df = load_ohlcv(code)
        if df is None or len(df) < 120:
            skipped += 1
            continue

        info   = meta.get(code, {})
        name   = info.get("name",   code)
        market = info.get("market", "KOSPI")

        if train_end is not None:
            df = df[df.index <= train_end]
            if len(df) < 120:
                skipped += 1
                continue

        if (i + 1) % 20 == 0:
            logger.info(f"[build] 진행 {i+1}/{len(tickers)} ({code} {name})")

        # 기술 피처 (시장 상대 강도 포함)
        tech = build_technical(df, market_df)

        # 라벨 3종
        labels_list = {}
        for lname, cfg in LABEL_CONFIGS.items():
            labels_list[lname] = make_label(df, cfg["days"],
                                            ret=cfg["ret"], dd=cfg["dd"])

        # 공통 유효 인덱스 (워밍업 60행 제외)
        valid_idx = tech.index
        for y in labels_list.values():
            valid_idx = valid_idx.intersection(y.dropna().index)
        valid_idx = valid_idx[60:]

        if len(valid_idx) < 60:
            skipped += 1
            continue

        # 피처 행렬 빌드
        if use_pit:
            q_history = get_quarterly_history(code, market)
            from .dart_client       import get_disclosure_features
            from .naver_news        import get_news_features
            from .investor_features import get_investor_features
            from .short_features    import get_short_features
            from .sector_features   import get_sector_features
            disc_news = {
                **get_disclosure_features(code),
                **get_news_features(code, name),
                **get_investor_features(code),
                **get_short_features(code),
                **get_sector_features(code),
            }
            X_df = build_full_matrix_pit(tech, q_history, disc_news, macro)
        else:
            static = build_static_features(code, name, market)
            X_df   = build_full_matrix(tech, static, macro)

        chunk = X_df.loc[valid_idx].values.astype(np.float32)
        all_X.append(chunk)
        all_dates.append(valid_idx.values)
        for k in LABEL_CONFIGS:
            all_labels[k].append(labels_list[k].loc[valid_idx].values.astype(int))
        used.append(code)

    if not all_X:
        logger.error("[build] 유효 데이터 없음")
        sys.exit(1)

    X           = np.vstack(all_X)
    dates_arr   = np.concatenate(all_dates)
    labels_dict = {k: np.concatenate(v) for k, v in all_labels.items()}

    # ⚠ 시간 전역 정렬 — walk-forward CV 의 전제.
    # 여기까지는 종목별 chunk 가 순서대로 쌓여 있을 뿐이라 행 순서 = 종목 순서다.
    # 그 상태로 walk_forward_cv/get_oof_predictions 가 X[:val_start] 처럼 '위치'를
    # 자르면, train 에 앞쪽 종목의 최신 데이터가 들어가고 val 에 뒤쪽 종목의 과거
    # 데이터가 들어간다 — 이름만 walk-forward 이고 실제로는 미래→과거 누수다.
    # 날짜로 전역 정렬해야 위치 슬라이싱이 곧 시간 분할이 된다.
    order       = np.argsort(dates_arr, kind="stable")
    X           = X[order]
    dates_arr   = dates_arr[order]
    labels_dict = {k: v[order] for k, v in labels_dict.items()}

    logger.info(f"[build] 종목 {len(used)}개 (스킵 {skipped}) | 샘플 {len(X):,} | 피처 {X.shape[1]}")
    logger.info(f"[build] 기간 {np.min(dates_arr)} ~ {np.max(dates_arr)} (시간순 정렬됨)")
    for k, y in labels_dict.items():
        logger.info(f"  {k:6s}: BUY {int(y.sum())} ({y.mean():.1%})")

    return X, dates_arr, labels_dict, FULL_COLS, used


# ═══════════════════════════════════════════════════════════════════════════
# Walk-forward CV
# ═══════════════════════════════════════════════════════════════════════════

def _purge_mask(dates: np.ndarray | None, train_end: int, val_start: int,
                purge_days: int) -> np.ndarray:
    """
    train 구간[0:train_end] 에서 val 시작 날짜의 purge_days 이내 행을 제거하는 마스크.

    라벨은 미래 purge_days 일 가격으로 만들어지므로, val 직전 train 샘플의 라벨이
    val 구간 가격을 물고 들어온다(look-ahead). 그 겹치는 창을 잘라낸다(purge/embargo).
    dates 가 없으면 purge 불가 → 전부 유지(마스크 all-True).
    데이터가 날짜 전역 정렬돼 있어 '행 N개' 가 아니라 '달력 N일' 로 잘라야 정확하다
    (여러 종목이 같은 날짜를 공유하므로).
    """
    if dates is None or purge_days <= 0 or train_end == 0:
        return np.ones(train_end, dtype=bool)
    val_first_date = dates[val_start]
    cutoff = val_first_date - np.timedelta64(purge_days, 'D')
    return dates[:train_end] <= cutoff


def walk_forward_cv(X: np.ndarray, y: np.ndarray, params: dict,
                    n_splits: int = 5, n_rounds: int = 200,
                    sample_weight: np.ndarray | None = None,
                    dates: np.ndarray | None = None,
                    purge_days: int = 0) -> dict:
    """
    시간 분할 walk-forward CV (purge/embargo 지원).

    ⚠ X 는 **스케일링 전(raw)** 을 넘길 것. 스케일러를 CV 밖에서 전체 데이터에 fit 하면
    검증 폴드의 평균·분산이 학습에 새어 지표가 부풀려진다(preprocessing leakage).
    폴드마다 train 구간에만 fit 해서 val 에 transform 한다.
    또 X 는 build_training_data 가 날짜로 전역 정렬해 반환한 것이어야 한다 — 그래야
    아래 위치 슬라이싱이 실제 시간 분할이 된다.

    purge_days > 0 이고 dates 가 주어지면, train 끝과 val 시작 사이에 라벨 지평선만큼
    간격을 둬 라벨 창이 val 을 물지 않게 한다(_purge_mask 참고).
    """
    import xgboost as xgb
    fold_size = len(X) // n_splits
    scores, aucs = [], []
    for fold in range(n_splits):
        val_start = fold * fold_size
        train_end = val_start
        if train_end < 60:
            continue
        mask = _purge_mask(dates, train_end, val_start, purge_days)
        X_tr_raw, y_tr = X[:train_end][mask], y[:train_end][mask]
        X_val_raw, y_val = X[val_start:val_start + fold_size], y[val_start:val_start + fold_size]
        if len(X_tr_raw) < 30 or len(X_val_raw) < 10 or len(np.unique(y_tr)) < 2:
            continue
        sw_tr = (sample_weight[:train_end][mask]
                 if sample_weight is not None else None)

        # 폴드 내 스케일링 — train 에만 fit
        fold_scaler = StandardScaler().fit(X_tr_raw)
        X_tr  = fold_scaler.transform(X_tr_raw).astype(np.float32)
        X_val = fold_scaler.transform(X_val_raw).astype(np.float32)

        spw = (1 - y_tr.mean()) / (y_tr.mean() + 1e-9)
        dtrain = xgb.DMatrix(X_tr, label=y_tr, weight=sw_tr)
        bst = xgb.train(
            {**params, "scale_pos_weight": spw},
            dtrain,
            num_boost_round=n_rounds,
            evals=[(xgb.DMatrix(X_val, label=y_val), "val")],
            verbose_eval=False, early_stopping_rounds=20,
        )
        proba = bst.predict(xgb.DMatrix(X_val))
        acc   = float(((proba >= 0.5).astype(int) == y_val).mean())
        try:
            from sklearn.metrics import roc_auc_score
            auc = float(roc_auc_score(y_val, proba))
        except Exception:
            auc = 0.5
        scores.append(acc); aucs.append(auc)

    if not scores:
        return {"auc": 0.5, "acc": 0.0}
    return {"auc": round(float(np.mean(aucs)), 4),
            "acc": round(float(np.mean(scores)), 4)}


# ═══════════════════════════════════════════════════════════════════════════
# OOF 예측 (스태킹용)
# ═══════════════════════════════════════════════════════════════════════════

def get_oof_predictions(X: np.ndarray, y: np.ndarray,
                        train_fn, dates: np.ndarray | None = None,
                        n_splits: int = 5, purge_days: int = 0) -> np.ndarray:
    """
    Walk-forward OOF 예측값 반환 (스태킹 메타피처용).

    ⚠ X 는 walk_forward_cv 와 같은 이유로 **스케일링 전(raw)** 을 넘긴다.
    dates 를 주면 폴드의 train 구간 실제 날짜를 train_fn 에 전달해 최신 가중치를
    계산하게 한다(예전에는 np.arange 를 가짜 날짜로 변환해 써서 가중치가 무의미했다).
    purge_days > 0 이면 walk_forward_cv 와 같은 purge/embargo 를 적용한다.

    train_fn(X_tr, y_tr, X_val, sw_tr) — 스케일링된 배열과 샘플 가중치를 받는다.
    """
    fold_size = len(X) // n_splits
    oof = np.zeros(len(X), dtype=np.float32)
    for fold in range(n_splits):
        val_start = fold * fold_size
        train_end = val_start
        if train_end < 60:
            continue
        mask = _purge_mask(dates, train_end, val_start, purge_days)
        X_tr_raw, y_tr = X[:train_end][mask], y[:train_end][mask]
        X_val_raw      = X[val_start:val_start + fold_size]
        if len(X_tr_raw) < 30 or len(np.unique(y_tr)) < 2:
            continue

        fold_scaler = StandardScaler().fit(X_tr_raw)
        X_tr  = fold_scaler.transform(X_tr_raw).astype(np.float32)
        X_val = fold_scaler.transform(X_val_raw).astype(np.float32)

        sw_tr = (compute_sample_weights(dates[:train_end][mask])
                 if dates is not None else None)

        preds = train_fn(X_tr, y_tr, X_val, sw_tr)
        oof[val_start:val_start + fold_size] = preds
    return oof


# ═══════════════════════════════════════════════════════════════════════════
# Optuna 튜닝 (선택)
# ═══════════════════════════════════════════════════════════════════════════

def optuna_tune(X, y, n_trials: int = 20,
                sample_weight=None, dates=None,
                purge_days: int = 0) -> tuple[dict, int]:
    """⚠ X 는 walk_forward_cv 로 그대로 넘어간다 — 스케일링 전(raw)을 줄 것."""
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        return _default_params()

    def objective(trial):
        p = {
            "objective": "binary:logistic", "eval_metric": "auc",
            "verbosity": 0, "seed": 42,
            "max_depth":        trial.suggest_int("max_depth", 3, 8),
            "eta":              trial.suggest_float("eta", 0.01, 0.3, log=True),
            "subsample":        trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
            "gamma":            trial.suggest_float("gamma", 0.0, 5.0),
            "lambda":           trial.suggest_float("lambda", 1e-3, 10.0, log=True),
            "alpha":            trial.suggest_float("alpha", 1e-3, 10.0, log=True),
        }
        nr = trial.suggest_int("n_rounds", 100, 400)
        return walk_forward_cv(X, y, p, n_rounds=nr,
                               sample_weight=sample_weight,
                               dates=dates, purge_days=purge_days)["auc"]

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = study.best_params.copy()
    n_rounds = best.pop("n_rounds", 200)
    best_params = {"objective": "binary:logistic", "eval_metric": "auc",
                   "verbosity": 0, "seed": 42, "device": "cuda", **best}
    return best_params, n_rounds


def _default_params() -> tuple[dict, int]:
    return {
        "objective": "binary:logistic", "eval_metric": "auc",
        "verbosity": 0, "seed": 42, "device": "cuda",
        "max_depth": 5, "eta": 0.03,
        "subsample": 0.8, "colsample_bytree": 0.8,
        "min_child_weight": 5, "gamma": 0.1,
        "lambda": 1.0, "alpha": 0.1,
    }, 300


# ═══════════════════════════════════════════════════════════════════════════
# SHAP 피처 중요도
# ═══════════════════════════════════════════════════════════════════════════

def compute_shap_importance(booster, X_sample: np.ndarray,
                            feature_names: list[str]) -> list[dict]:
    """SHAP 평균 절댓값 기준 피처 중요도 (상위 20개)."""
    try:
        import shap
        explainer   = shap.TreeExplainer(booster)
        shap_values = explainer.shap_values(X_sample)
        mean_abs    = np.abs(shap_values).mean(axis=0)
        pairs = sorted(zip(feature_names, mean_abs.tolist()),
                       key=lambda x: -x[1])
        return [{"feature": f, "shap_importance": round(v, 6)}
                for f, v in pairs[:20]]
    except Exception as e:
        logger.warning(f"[shap] 계산 실패: {e}. pip install shap 확인.")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# 메인 학습
# ═══════════════════════════════════════════════════════════════════════════

def train_all(tickers: list[str], train_end: str = "",
              n_trials: int = 0, skip_optuna: bool = False,
              use_pit: bool = True,
              labels: list[str] | None = None):
    import xgboost as xgb
    # StandardScaler 는 모듈 레벨에서 임포트한다 (CV 폴드에서도 쓰이므로)
    from sklearn.linear_model  import LogisticRegression

    # LightGBM 옵션
    try:
        import lightgbm as lgb
        HAS_LGB = True
    except ImportError:
        logger.warning("[train] LightGBM 미설치 — XGBoost 단독 모드. pip install lightgbm")
        HAS_LGB = False

    # CatBoost 옵션
    try:
        from catboost import CatBoostClassifier
        HAS_CAT = True
    except ImportError:
        logger.warning("[train] CatBoost 미설치 — 앙상블에서 제외. pip install catboost")
        HAS_CAT = False

    train_end_dt = pd.Timestamp(train_end) if train_end else None
    active_labels = labels or list(LABEL_CONFIGS.keys())

    logger.info("=" * 60)
    logger.info(f"■ 학습 시작 — 피처 {len(FULL_COLS)}개 | 라벨 {active_labels}")
    logger.info(f"  학습 기간  : ~ {train_end or '전체'}")
    logger.info(f"  Optuna     : {'스킵' if skip_optuna else f'{n_trials}회'}")
    logger.info(f"  PIT 재무   : {'활성' if use_pit else '비활성'}")
    logger.info(f"  LightGBM   : {'활성' if HAS_LGB else '비활성'}")
    logger.info(f"  CatBoost   : {'활성' if HAS_CAT else '비활성'}")
    logger.info("=" * 60)

    # KOSPI 시장 데이터 (상대 강도 피처용)
    from .feature_v2 import get_market_ohlcv
    market_df = get_market_ohlcv()
    if market_df is None:
        logger.warning("[train] KOSPI 데이터 없음 — 시장 상대 강도 피처 비활성")

    # 데이터 빌드
    X_raw, dates_arr, labels_dict, feature_names, used_tickers = build_training_data(
        tickers, train_end=train_end_dt, use_pit=use_pit, market_df=market_df)

    # 정규화 — **배포 모델 전용**.
    # 배포 모델은 전체 학습 데이터를 쓰는 게 맞으므로 여기서 fit 해 저장한다.
    # 단 CV·OOF 에는 X_scaled 를 넘기면 안 된다(검증 폴드 통계가 새어 지표가 부풀려짐).
    # 그쪽은 X_raw 를 받아 폴드 안에서 train 구간에만 fit 한다.
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw).astype(np.float32)

    # 샘플 가중치 (최신 데이터 우대)
    sample_weight = compute_sample_weights(dates_arr, half_life_days=180)

    labels_dict = {k: v for k, v in labels_dict.items() if k in active_labels}

    # 라벨별 모델 학습
    reports     = {}
    shap_report = {}

    for label_name, y in labels_dict.items():
        logger.info(f"\n[train] === {label_name.upper()} 모델 학습 ===")
        buy_ratio = y.mean()
        if buy_ratio < 0.02 or buy_ratio > 0.5:
            logger.warning(f"[train] {label_name} BUY 비율 이상({buy_ratio:.1%}) — 스킵")
            continue

        # 이 라벨의 지평선(일) — CV 폴드 경계에서 purge/embargo 로 잘라낼 창.
        # 라벨이 미래 이만큼의 가격으로 만들어지므로, val 직전 train 샘플이 val 을 물지
        # 않게 이 일수만큼 간격을 둔다.
        purge_days = LABEL_CONFIGS[label_name]["days"]

        # ── 파라미터 ───────────────────────────────────────────────────
        if skip_optuna or n_trials == 0:
            params, n_rounds = _default_params()
        else:
            logger.info(f"[train] Optuna {n_trials}회 튜닝...")
            params, n_rounds = optuna_tune(X_raw, y, n_trials,
                                           sample_weight=sample_weight,
                                           dates=dates_arr, purge_days=purge_days)
            logger.info(f"[train] 최적: {params}")

        # ── CV ────────────────────────────────────────────────────────
        # raw 를 넘긴다 — 스케일러는 폴드 안에서 train 구간에만 fit 된다.
        cv = walk_forward_cv(X_raw, y, params, n_rounds=n_rounds,
                             sample_weight=sample_weight,
                             dates=dates_arr, purge_days=purge_days)
        logger.info(f"  CV  AUC={cv['auc']:.4f}  Acc={cv['acc']:.4f} (purge {purge_days}d)")

        spw = (1 - buy_ratio) / (buy_ratio + 1e-9)

        # ── XGBoost (Focal Loss) ───────────────────────────────────────
        dtrain_xgb = xgb.DMatrix(X_scaled, label=y, weight=sample_weight)
        booster = xgb.train(
            {**params, "scale_pos_weight": spw},
            dtrain_xgb,
            num_boost_round=n_rounds,
            obj=focal_loss_objective(gamma=2.0),
            verbose_eval=False,
        )
        model_path_xgb = MODEL_DIR / f'xgb_v2_{label_name}.json'
        booster.save_model(str(model_path_xgb))
        logger.info(f"  XGB 저장: {model_path_xgb}")

        # ── LightGBM ──────────────────────────────────────────────────
        if HAS_LGB:
            lgb_params = {
                "objective": "binary", "metric": "auc",
                "verbosity": -1, "seed": 42,
                "num_leaves":       31,
                "learning_rate":    params.get("eta", 0.03),
                "subsample":        params.get("subsample", 0.8),
                "colsample_bytree": params.get("colsample_bytree", 0.8),
                "min_child_weight": params.get("min_child_weight", 5),
                "scale_pos_weight": spw,
            }
            dtrain_lgb = lgb.Dataset(X_scaled, label=y, weight=sample_weight)
            lgb_model  = lgb.train(lgb_params, dtrain_lgb,
                                   num_boost_round=n_rounds)
            model_path_lgb = MODEL_DIR / f'lgb_v2_{label_name}.txt'
            lgb_model.save_model(str(model_path_lgb))
            logger.info(f"  LGB 저장: {model_path_lgb}")

        # ── CatBoost ──────────────────────────────────────────────────
        if HAS_CAT:
            cat_model = CatBoostClassifier(
                iterations=n_rounds,
                learning_rate=params.get("eta", 0.03),
                depth=params.get("max_depth", 5),
                eval_metric='AUC',
                class_weights=[1.0, float(spw)],
                random_seed=42, verbose=0,
            )
            cat_model.fit(X_scaled, y, sample_weight=sample_weight)
            model_path_cat = MODEL_DIR / f'cat_v2_{label_name}.cbm'
            cat_model.save_model(str(model_path_cat))
            logger.info(f"  CAT 저장: {model_path_cat}")

        # ── 스태킹 메타-러너 ──────────────────────────────────────────
        logger.info(f"  스태킹 OOF 생성 중...")

        # sw 는 get_oof_predictions 가 폴드의 실제 날짜로 계산해 넘겨준다.
        # (예전에는 여기서 np.arange 를 datetime64 로 캐스팅해 1970-01-01 부터의
        #  가짜 날짜를 만들었고, 행 순서가 시간순도 아니어서 가중치가 무의미했다.)
        def xgb_train_fn(Xtr, ytr, Xval, sw):
            spw_ = (1 - ytr.mean()) / (ytr.mean() + 1e-9)
            d    = xgb.DMatrix(Xtr, label=ytr, weight=sw)
            b    = xgb.train({**params, "scale_pos_weight": spw_}, d,
                             num_boost_round=n_rounds, verbose_eval=False)
            return b.predict(xgb.DMatrix(Xval))

        oof_xgb = get_oof_predictions(X_raw, y, xgb_train_fn, dates=dates_arr, purge_days=purge_days)

        meta_cols = [oof_xgb]
        if HAS_LGB:
            def lgb_train_fn(Xtr, ytr, Xval, sw):
                spw_ = (1 - ytr.mean()) / (ytr.mean() + 1e-9)
                dtr  = lgb.Dataset(Xtr, label=ytr, weight=sw)
                lm   = lgb.train({**lgb_params, "scale_pos_weight": spw_},
                                 dtr, num_boost_round=n_rounds)
                return lm.predict(Xval)
            meta_cols.append(get_oof_predictions(X_raw, y, lgb_train_fn,
                                                 dates=dates_arr, purge_days=purge_days))

        if HAS_CAT:
            def cat_train_fn(Xtr, ytr, Xval, sw):
                spw_ = (1 - ytr.mean()) / (ytr.mean() + 1e-9)
                cm   = CatBoostClassifier(
                    iterations=n_rounds,
                    learning_rate=params.get("eta", 0.03),
                    depth=params.get("max_depth", 5),
                    class_weights=[1.0, float(spw_)],
                    random_seed=42, verbose=0,
                )
                cm.fit(Xtr, ytr, sample_weight=sw)
                return cm.predict_proba(Xval)[:, 1]
            meta_cols.append(get_oof_predictions(X_raw, y, cat_train_fn,
                                                 dates=dates_arr, purge_days=purge_days))

        meta_X = np.column_stack(meta_cols) if len(meta_cols) > 1 else meta_cols[0].reshape(-1, 1)

        # 스태킹 학습 (OOF != 0인 구간만)
        valid_meta = meta_X.sum(axis=1) != 0
        Xm = meta_X[valid_meta] if valid_meta.sum() > 100 else meta_X
        ym = y[valid_meta]      if valid_meta.sum() > 100 else y

        meta_model = LogisticRegression(C=1.0, max_iter=500)
        meta_model.fit(Xm, ym)

        meta_path = MODEL_DIR / f'meta_v2_{label_name}.pkl'
        with open(meta_path, 'wb') as f:
            pickle.dump({"model": meta_model, "calibrator": None,
                         "has_lgb": HAS_LGB, "has_cat": HAS_CAT}, f)
        logger.info(f"  Meta 저장: {meta_path}")

        # ── SHAP 중요도 (샘플 1500행 — 주간 재학습 시 자동 생성) ─────
        try:
            rs  = np.random.RandomState(42)
            idx = rs.choice(len(X_scaled), size=min(1500, len(X_scaled)), replace=False)
            shap_report[label_name] = compute_shap_importance(
                booster, X_scaled[idx], feature_names)
            logger.info(f"  SHAP 중요도 계산 완료 ({len(shap_report[label_name])}개 피처)")
        except Exception as e:
            logger.warning(f"  SHAP 계산 스킵: {e}")
            shap_report[label_name] = []

        # ── fscore 중요도 (상위 5) ───────────────────────────────────
        scores = booster.get_fscore()
        total  = sum(scores.values()) or 1
        imps   = [(feature_names[i], scores.get(f"f{i}", 0) / total)
                  for i in range(len(feature_names))]
        top5   = sorted(imps, key=lambda x: -x[1])[:5]

        reports[label_name] = {
            "cv_auc": cv["auc"], "cv_acc": cv["acc"],
            "buy_ratio": round(float(buy_ratio), 4),
            "best_params": params, "n_rounds": n_rounds,
            "has_lgb": HAS_LGB,
            "has_cat": HAS_CAT,
            "top_features_fscore": [{"feature": fn, "importance": round(imp, 4)}
                                     for fn, imp in top5],
        }

    # ── 공용 파일 저장 ────────────────────────────────────────────────────
    with open(MODEL_DIR / 'scaler_v2.pkl',        'wb') as f:
        pickle.dump(scaler, f)
    with open(MODEL_DIR / 'feature_list_v2.json', 'w', encoding='utf-8') as f:
        json.dump(feature_names, f, ensure_ascii=False, indent=2)
    with open(MODEL_DIR / 'label_configs_v2.json','w', encoding='utf-8') as f:
        json.dump(LABEL_CONFIGS, f, ensure_ascii=False, indent=2)
    with open(MODEL_DIR / 'shap_importance_v2.json','w', encoding='utf-8') as f:
        json.dump(shap_report, f, ensure_ascii=False, indent=2)

    full_report = {
        "trained_at":  datetime.now().isoformat(),
        "train_end":   train_end or "all",
        "n_tickers":   len(used_tickers),
        "n_samples":   int(len(X_raw)),
        "n_features":  int(X_raw.shape[1]),
        "use_pit":     use_pit,
        # 검증 설계 — CV 지표를 어떤 조건에서 얻었는지 아티팩트에 못 박는다.
        # (2026-07-17 이전 모델은 셋 다 없었다: 행이 종목순이라 walk-forward 가
        #  시간 분할이 아니었고, 스케일러를 CV 전에 전체 fit 했으며, PIT 기한이
        #  feature_v2 45d / kr_finance_client 90d 로 어긋나 있었다.)
        "cv_time_ordered":     True,
        "cv_scaler_in_fold":   True,
        # CV 폴드 경계에 라벨 지평선(라벨별 3/5/14일)만큼 purge/embargo 를 적용해
        # val 직전 train 샘플의 라벨이 val 구간 가격을 물지 않게 한다.
        "cv_purge_embargo":    True,
        "pit_filing_lag_days": PIT_FILING_LAG_DAYS,
        "data_start":          str(np.min(dates_arr)),
        "data_end":            str(np.max(dates_arr)),
        "labels":      reports,
        "tickers":     used_tickers,
    }
    with open(MODEL_DIR / 'train_report_v2.json', 'w', encoding='utf-8') as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)

    # 성능 이력 누적 저장
    history_path = MODEL_DIR / 'ml_performance_history.json'
    history_entry = {
        "trained_at": full_report["trained_at"],
        "n_tickers":  full_report["n_tickers"],
        "n_samples":  full_report["n_samples"],
        "n_features": full_report["n_features"],
        "labels": {
            k: {"cv_auc": v["cv_auc"], "cv_acc": v["cv_acc"], "buy_ratio": v["buy_ratio"]}
            for k, v in reports.items()
        },
    }
    try:
        hist = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else []
        hist.insert(0, history_entry)
        history_path.write_text(json.dumps(hist[:100], ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        logger.warning(f"성능 이력 저장 실패: {e}")

    logger.info("=" * 60)
    logger.info("■ 학습 완료")
    for name, rpt in reports.items():
        logger.info(f"  {name:6s}: AUC {rpt['cv_auc']:.3f} | BUY {rpt['buy_ratio']:.1%} | LGB={rpt['has_lgb']} CAT={rpt['has_cat']}")
    logger.info(f"  저장: {MODEL_DIR}")
    logger.info("=" * 60)
    return full_report


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="앙상블 모델 학습 (53피처 x 3라벨)")
    p.add_argument('--source',     choices=['local'], default='local')
    p.add_argument('--train-end',  default="")
    p.add_argument('--top',        type=int, default=None)
    p.add_argument('--tickers',    nargs='+', default=None)
    p.add_argument('--trials',     type=int,  default=0)
    p.add_argument('--skip-optuna',action='store_true')
    p.add_argument('--labels',     nargs='+', choices=['daily','short','swing'],
                   default=None,   help='학습할 라벨 (기본: 전체). 예: --labels daily short')
    p.add_argument('--no-pit',     action='store_true',
                   help='PIT 재무 매칭 비활성화 (빠른 학습)')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.tickers:
        tickers = [t.replace('.KS','').replace('.KQ','') for t in args.tickers]
    else:
        tickers = list_collected()
        if args.top:
            tickers = tickers[:args.top]
    logger.info(f"[main] 대상: {len(tickers)}개 종목")
    try:
        train_all(
            tickers=tickers, train_end=args.train_end,
            n_trials=args.trials, skip_optuna=args.skip_optuna,
            use_pit=not args.no_pit,
            labels=args.labels,
        )
    except Exception as e:
        logger.error(f"학습 실패: {e}", exc_info=True)
        try:
            import sys as _sys; _sys.path.insert(0, str(Path(__file__).parent.parent))
            from notify.send import notify_error
            notify_error("train_v2 학습", str(e))
        except Exception:
            pass
        raise
