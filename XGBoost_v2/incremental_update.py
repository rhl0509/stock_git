"""
XGBoost_v2/incremental_update.py — 일별 XGBoost 모델 미세조정.

전체 재학습(월 1회) 사이에 최근 데이터로 모델을 가볍게 업데이트.
- 최근 N일 중 라벨이 확정된 데이터만 사용 (daily=3일, short=5일, swing=14일 이후)
- 각 라벨 모델에 30 round warm-start
- 스케일러/피처 목록은 그대로 유지 (재학습 시에만 갱신)

실행:
  .venv64\\Scripts\\python.exe -m XGBoost_v2.incremental_update
  (작업 스케줄러: 매일 08:40, daily_recommend 전)
"""
import json, logging, pickle, sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent
MODEL_DIR = Path(__file__).parent / "model"
OHLCV_DIR = Path(__file__).parent / "data" / "ohlcv"

LABEL_CONFIGS = {
    "daily": {"days":  3, "ret": 0.02, "dd": -0.015},
    "short": {"days":  5, "ret": 0.03, "dd": -0.02},
    "swing": {"days": 14, "ret": 0.07, "dd": -0.04},
}
INCREMENTAL_ROUNDS = 30   # warm-start 추가 라운드
LOOKBACK_DAYS      = 60   # 최근 N일 데이터만 사용


def _make_label(df: pd.DataFrame, days: int,
                ret_thr: float, dd_thr: float) -> pd.Series:
    close = df["close"]; low = df["low"]
    labels = pd.Series(np.nan, index=close.index)
    for i in range(len(close) - days):
        ret = (close.iloc[i + days] - close.iloc[i]) / close.iloc[i]
        mdd = (low.iloc[i:i + days].min() - close.iloc[i]) / close.iloc[i]
        labels.iloc[i] = 1.0 if (ret > ret_thr and mdd > dd_thr) else 0.0
    return labels


def _load_recent_data(features: list, scaler) -> tuple[np.ndarray, dict]:
    """최근 LOOKBACK_DAYS 데이터에서 피처 행렬과 라벨 dict 반환."""
    from .feature_v2 import build_technical, build_static_features, build_full_matrix, get_macro, get_market_ohlcv

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    macro  = get_macro()
    market_df = get_market_ohlcv()

    all_X: list[np.ndarray] = []
    all_labels = {k: [] for k in LABEL_CONFIGS}
    used = 0

    meta_path = Path(__file__).parent / "data" / "ticker_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

    for parquet in OHLCV_DIR.glob("*.parquet"):
        code = parquet.stem
        try:
            df = pd.read_parquet(parquet)
            df.index = pd.to_datetime(df.index)
            df = df[df.index >= pd.Timestamp(cutoff)]
            if len(df) < max(cfg["days"] for cfg in LABEL_CONFIGS.values()) + 10:
                continue

            name   = meta.get(code, {}).get("name", code)
            market = meta.get(code, {}).get("market", "KOSPI")

            tech   = build_technical(df, market_df)
            static = build_static_features(code, name, market)
            X_df   = build_full_matrix(tech, static, macro)

            for col in features:
                if col not in X_df.columns:
                    X_df[col] = 0.0
            X_df = X_df[features].replace([np.inf, -np.inf], 0).fillna(0)

            label_series = {}
            valid_idx = X_df.index
            for lname, cfg in LABEL_CONFIGS.items():
                y = _make_label(df, cfg["days"], cfg["ret"], cfg["dd"])
                valid_idx = valid_idx.intersection(y.dropna().index)
                label_series[lname] = y

            valid_idx = valid_idx[10:]  # 워밍업 제외
            if len(valid_idx) < 5:
                continue

            X_scaled = scaler.transform(X_df.loc[valid_idx].values.astype(np.float32))
            all_X.append(X_scaled)
            for lname in LABEL_CONFIGS:
                all_labels[lname].append(label_series[lname].loc[valid_idx].values.astype(int))
            used += 1

        except Exception as e:
            logger.debug(f"[incr] {code}: {e}")

    if not all_X:
        return np.array([]), {}

    X = np.vstack(all_X)
    y_dict = {k: np.concatenate(v) for k, v in all_labels.items()}
    logger.info(f"[incr] 데이터 로드: {used}종목 | {len(X):,}샘플")
    return X, y_dict


def run_incremental() -> bool:
    import xgboost as xgb

    scaler_path = MODEL_DIR / "scaler_v2.pkl"
    feat_path   = MODEL_DIR / "feature_list_v2.json"

    if not scaler_path.exists() or not feat_path.exists():
        logger.error("[incr] 모델 없음 — run_monthly.bat으로 전체 학습 먼저 필요")
        return False

    with open(scaler_path, "rb") as f:
        scaler = pickle.load(f)
    features = json.loads(feat_path.read_text(encoding="utf-8"))

    X, y_dict = _load_recent_data(features, scaler)
    if len(X) == 0:
        logger.error("[incr] 유효 데이터 없음")
        return False

    updated = []
    for label, cfg in LABEL_CONFIGS.items():
        xgb_path = MODEL_DIR / f"xgb_v2_{label}.json"
        if not xgb_path.exists():
            logger.warning(f"[incr] {label} 모델 없음, 스킵")
            continue

        y = y_dict[label]
        if len(np.unique(y)) < 2:
            logger.warning(f"[incr] {label} 라벨 불균형 심각, 스킵")
            continue

        booster = xgb.Booster()
        booster.load_model(str(xgb_path))

        spw    = float((1 - y.mean()) / (y.mean() + 1e-9))
        dtrain = xgb.DMatrix(X, label=y)

        # warm-start: 기존 모델에서 추가 라운드 학습
        booster = xgb.train(
            {"scale_pos_weight": spw, "verbosity": 0},
            dtrain,
            num_boost_round=INCREMENTAL_ROUNDS,
            xgb_model=booster,
            verbose_eval=False,
        )
        booster.save_model(str(xgb_path))
        updated.append(label)
        logger.info(f"[incr] {label} +{INCREMENTAL_ROUNDS}rounds 완료")

    if updated:
        logger.info(f"[incr] 업데이트 완료: {updated}")
        try:
            sys.path.insert(0, str(ROOT))
            from notify.send import send_message_to_self
            now = datetime.now().strftime("%m/%d %H:%M")
            send_message_to_self(
                f"🔄 [{now}] 모델 미세조정 완료\n라벨: {', '.join(updated)}\n+{INCREMENTAL_ROUNDS} rounds",
                link_url="http://localhost:5000/stock_train_report"
            )
        except Exception:
            pass
    return bool(updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ok = run_incremental()
    sys.exit(0 if ok else 1)
