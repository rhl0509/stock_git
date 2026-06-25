"""
train.py
──────────────────────────────────────────────────────────────────────────────
XGBoost 모델 학습 스크립트.

이 파일은 Flask 서버와 별개로 64비트 Python 에서 단독 실행합니다.
학습 완료 후 model/ 디렉토리에 파일을 저장하고
Flask 서버에서 POST /ml/reload 를 호출하면 즉시 반영됩니다.

저장 파일:
  model/xgboost_model.json   — XGBoost Booster 모델
  model/scaler.pkl           — StandardScaler
  model/feature_list.json    — 피처 이름 순서
  model/label_config.json    — 라벨 정의 및 임계값
  model/train_report.json    — 학습 결과 리포트

실행 방법:
  python train.py
  python train.py --tickers 005930.KS 000660.KS 035720.KS
  python train.py --source yfinance --tickers 005930.KS 000660.KS
  python train.py --target-days 3 --threshold 0.55

요구사항 (64비트 Python + venv_train):
  pip install xgboost==2.1.4 scikit-learn pandas numpy requests
              beautifulsoup4 python-dotenv yfinance lxml
──────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import json
import pickle
import argparse
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()   # .env 파일 로드 (BOK_API_KEY, DART_API_KEY 등)

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ── 경로 설정 ─────────────────────────────────────────────────────────────
ROOT_DIR  = Path(__file__).parent
MODEL_DIR = ROOT_DIR / 'model'
MODEL_DIR.mkdir(exist_ok=True)

# ── 기본 학습 설정 ─────────────────────────────────────────────────────────
DEFAULT_TICKERS = ["005930.KS"]
DEFAULT_SOURCE  = "yfinance"
TARGET_DAYS     = 5
BUY_THRESHOLD   = 0.03
SELL_THRESHOLD  = -0.02
OHLCV_COUNT     = 600
MIN_ROWS        = 120


# ═════════════════════════════════════════════════════════════════════════════
# 1. 데이터 수집
# ═════════════════════════════════════════════════════════════════════════════

def fetch_ohlcv_kiwoom(ticker: str, count: int = OHLCV_COUNT) -> pd.DataFrame | None:
    """키움 kiwoom_worker.get_ohlcv() 로 일봉 데이터 수집."""
    try:
        sys.path.insert(0, str(ROOT_DIR))
        from kiwoom_client import kiwoom
        if kiwoom.get_login_state() != 1:
            logger.warning("[data] 키움 로그인 안됨 → yfinance 폴백")
            return None
        df = kiwoom.get_ohlcv(ticker, count=count)
        if df is not None and not df.empty and len(df) >= MIN_ROWS:
            logger.info(f"[data] 키움 {ticker}: {len(df)}행")
            return df
    except Exception as e:
        logger.warning(f"[data] 키움 실패 ({ticker}): {e}")
    return None


def fetch_ohlcv_yfinance(ticker: str, count: int = OHLCV_COUNT) -> pd.DataFrame | None:
    """yfinance 로 일봉 데이터 수집."""
    try:
        import yfinance as yf
        end   = datetime.now()
        start = end - timedelta(days=int(count * 1.5))
        raw   = yf.Ticker(ticker).history(start=start, end=end)
        if raw is None or raw.empty:
            return None
        df         = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index   = pd.to_datetime(df.index).tz_localize(None)
        df         = df.sort_index()
        logger.info(f"[data] yfinance {ticker}: {len(df)}행")
        return df
    except Exception as e:
        logger.warning(f"[data] yfinance 실패 ({ticker}): {e}")
    return None


def fetch_ohlcv(ticker: str, source: str = DEFAULT_SOURCE,
                count: int = OHLCV_COUNT) -> pd.DataFrame | None:
    """OHLCV 수집 진입점. 키움 우선 → yfinance 폴백."""
    if source == "kiwoom":
        df = fetch_ohlcv_kiwoom(ticker, count)
        if df is not None and len(df) >= MIN_ROWS:
            return df
    yfcode = ticker if "." in ticker else ticker + ".KS"
    return fetch_ohlcv_yfinance(yfcode, count)


# ═════════════════════════════════════════════════════════════════════════════
# 2. 피처 빌드 (API 호출 없이 로컬 계산만 사용 — 속도 최적화)
# ═════════════════════════════════════════════════════════════════════════════

def build_features_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    학습용 피처 빌드.

    ⚡ 속도 최적화: API 호출(BOK/DART/KIS/뉴스) 없이
    로컬 numpy/pandas 계산만 사용합니다.

    수급/거시/공시/뉴스 피처는 실시간 예측(signal.py)에서 추가되며,
    학습 시에는 기술적 지표만으로 베이스 모델을 훈련합니다.

    학습 → model/ 저장 → Flask signal.py 에서 실시간 피처 추가 반영.
    """
    return _build_numpy_features(df)


def _build_numpy_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    pandas/numpy 기반 기술적 지표 피처.
    외부 API 호출 없음 — 학습 속도 최적화.
    """
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    feats = {}

    # ── 수익률 ───────────────────────────────────────────────────────────
    for d in [1, 5, 20]:
        feats[f"ret_{d}d"] = c.pct_change(d)

    # ── 이동평균 이격도 ──────────────────────────────────────────────────
    for w in [5, 10, 20, 60]:
        ma = c.rolling(w).mean()
        feats[f"ma{w}_gap"] = c / (ma + 1e-9) - 1

    # ── RSI(14) ──────────────────────────────────────────────────────────
    delta    = c.diff()
    gain     = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss     = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
    feats["rsi_14"] = 100 - 100 / (1 + gain / (loss + 1e-9))

    # ── MACD(12, 26, 9) ──────────────────────────────────────────────────
    ema12    = c.ewm(span=12, adjust=False).mean()
    ema26    = c.ewm(span=26, adjust=False).mean()
    macd     = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    feats["macd"]      = macd
    feats["macd_hist"] = macd - macd_sig

    # ── 볼린저 %B ────────────────────────────────────────────────────────
    ma20  = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    feats["bb_pct"] = (c - (ma20 - 2 * std20)) / (4 * std20 + 1e-9)

    # ── 거래량 비율 ───────────────────────────────────────────────────────
    feats["vol_ratio_5"]  = v / (v.rolling(5).mean()  + 1e-9)
    feats["vol_ratio_20"] = v / (v.rolling(20).mean() + 1e-9)

    # ── ATR 비율 ─────────────────────────────────────────────────────────
    prev_c = c.shift(1)
    tr     = pd.concat([h - l,
                        (h - prev_c).abs(),
                        (l - prev_c).abs()], axis=1).max(axis=1)
    feats["atr_ratio"] = tr.rolling(14).mean() / (c + 1e-9)

    # ── OBV z-score ──────────────────────────────────────────────────────
    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    feats["obv_norm"] = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-9)

    # ── 20일 채널 위치 ────────────────────────────────────────────────────
    hi20  = h.rolling(20).max()
    lo20  = l.rolling(20).min()
    feats["chan_pos"] = (c - lo20) / (hi20 - lo20 + 1e-9)

    feat_df = pd.DataFrame(feats, index=df.index)
    feat_df = feat_df.replace([np.inf, -np.inf], 0).fillna(0)
    return feat_df


# ═════════════════════════════════════════════════════════════════════════════
# 3. 라벨 생성
# ═════════════════════════════════════════════════════════════════════════════

def make_labels(close: pd.Series, target_days: int,
                buy_thr: float, sell_thr: float) -> pd.Series:
    """
    3-class 라벨 생성.
      2 = BUY  (n일 후 수익률 > buy_thr)
      0 = SELL (n일 후 수익률 < sell_thr)
      1 = HOLD (그 외)
    마지막 target_days 행은 NaN → 학습에서 제외.
    """
    future_ret = close.shift(-target_days) / close - 1
    labels     = pd.Series(1, index=close.index, name="label")
    labels[future_ret >  buy_thr]  = 2
    labels[future_ret <  sell_thr] = 0
    labels[future_ret.isna()]      = np.nan
    return labels


# ═════════════════════════════════════════════════════════════════════════════
# 4. Walk-forward 교차검증
# ═════════════════════════════════════════════════════════════════════════════

def walk_forward_cv(X: np.ndarray, y: np.ndarray,
                    n_splits: int = 5) -> dict:
    """
    시계열 Walk-forward 교차검증.
    train = [:val_start], val = [val_start:val_end] 구조로
    미래 데이터 누수를 완전히 차단합니다.
    """
    try:
        import xgboost as xgb
    except ImportError:
        logger.error("[cv] xgboost 미설치 — pip install xgboost==2.1.4")
        return {'accuracy': 0.0, 'std': 0.0, 'fold_scores': []}

    fold_size   = len(X) // n_splits
    fold_scores = []

    for fold in range(n_splits):
        val_start = fold * fold_size
        val_end   = val_start + fold_size
        train_end = val_start

        if train_end < 60:
            continue

        X_tr, y_tr   = X[:train_end],        y[:train_end]
        X_val, y_val = X[val_start:val_end],  y[val_start:val_end]

        if len(X_tr) < 30 or len(X_val) < 10:
            continue
        if len(np.unique(y_tr)) < 2:
            continue

        dtrain = xgb.DMatrix(X_tr, label=y_tr)
        dval   = xgb.DMatrix(X_val)

        params = {
            "objective":        "multi:softprob",
            "num_class":        3,
            "max_depth":        4,
            "eta":              0.05,
            "subsample":        0.8,
            "colsample_bytree": 0.8,
            "eval_metric":      "mlogloss",
            "verbosity":        0,
            "seed":             42,
        }
        booster = xgb.train(params, dtrain, num_boost_round=100, verbose_eval=False)

        # predict → (n, 3) 확률 → argmax → 클래스
        proba = booster.predict(dval).reshape(-1, 3)
        preds = proba.argmax(axis=1)
        acc   = float((preds == y_val).mean())
        fold_scores.append(acc)
        logger.info(f"  Fold {fold + 1}/{n_splits}: acc={acc:.3f} "
                    f"(train={len(X_tr)}, val={len(X_val)})")

    if not fold_scores:
        return {'accuracy': 0.0, 'std': 0.0, 'fold_scores': []}

    return {
        'accuracy':    round(float(np.mean(fold_scores)), 4),
        'std':         round(float(np.std(fold_scores)),  4),
        'fold_scores': [round(s, 4) for s in fold_scores],
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. 최종 학습 & 저장
# ═════════════════════════════════════════════════════════════════════════════

def train_and_save(
    tickers:     list[str],
    source:      str   = DEFAULT_SOURCE,
    target_days: int   = TARGET_DAYS,
    buy_thr:     float = BUY_THRESHOLD,
    sell_thr:    float = SELL_THRESHOLD,
    pred_thr:    float = 0.60,
    n_splits:    int   = 5,
):
    """
    다중 종목 OHLCV 를 합쳐 XGBoost Booster 를 학습하고 model/ 에 저장합니다.

    저장 형식: xgb.Booster.save_model() → JSON
    로드 형식: signal.py 에서 xgb.Booster().load_model() 로 로드
    """
    try:
        import xgboost as xgb
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        logger.error("xgboost 또는 scikit-learn 미설치.\n"
                     "  pip install xgboost==2.1.4 scikit-learn")
        sys.exit(1)

    # ── 1. 데이터 수집 & 피처 빌드 ─────────────────────────────────────
    all_X, all_y = [], []
    used_tickers = []
    feat_df      = None

    for ticker in tickers:
        logger.info(f"[train] {ticker} 데이터 수집 중...")
        df = fetch_ohlcv(ticker, source=source)

        if df is None or len(df) < MIN_ROWS:
            n = len(df) if df is not None else 0
            logger.warning(f"[train] {ticker} 데이터 부족 ({n}행) — 스킵")
            continue

        feat_df = build_features_from_df(df)
        labels  = make_labels(df["close"], target_days, buy_thr, sell_thr)

        # 공통 인덱스 + 워밍업(앞 60행) 제거
        common = feat_df.index.intersection(labels.dropna().index)[60:]

        if len(common) < 60:
            logger.warning(f"[train] {ticker} 유효 샘플 부족 — 스킵")
            continue

        X_t = feat_df.loc[common].values.astype(np.float32)
        y_t = labels.loc[common].values.astype(int)

        all_X.append(X_t)
        all_y.append(y_t)
        used_tickers.append(ticker)
        logger.info(f"[train] {ticker}: 피처 {X_t.shape[1]}개, 샘플 {len(X_t)}개")

    if not all_X:
        logger.error("[train] 유효 데이터 없음. 종료.")
        sys.exit(1)

    X             = np.vstack(all_X)
    y             = np.concatenate(all_y)
    feature_names = feat_df.columns.tolist()

    logger.info(f"[train] 전체 샘플: {len(X):,}개 | 피처: {X.shape[1]}개")
    logger.info(f"[train] 라벨 분포: SELL={int((y==0).sum())} "
                f"HOLD={int((y==1).sum())} BUY={int((y==2).sum())}")

    # ── 2. 정규화 ────────────────────────────────────────────────────────
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X).astype(np.float32)

    # ── 3. Walk-forward 교차검증 ─────────────────────────────────────────
    logger.info(f"[train] Walk-forward {n_splits}-Fold 교차검증 시작...")
    cv_result = walk_forward_cv(X_scaled, y, n_splits=n_splits)
    logger.info(
        f"[train] CV 결과: "
        f"acc={cv_result['accuracy']:.3f}±{cv_result['std']:.3f} | "
        f"folds={cv_result['fold_scores']}"
    )

    # ── 4. 전체 데이터로 최종 학습 (xgb.Booster 직접 사용) ─────────────
    # XGBClassifier.save_model() 은 버전에 따라 _estimator_type 오류 발생.
    # xgb.Booster 를 직접 사용하면 버전 무관하게 안정적으로 저장/로드 가능.
    logger.info("[train] 최종 모델 학습 중...")

    dtrain = xgb.DMatrix(X_scaled, label=y)
    params = {
        "objective":        "multi:softprob",
        "num_class":        3,
        "max_depth":        5,
        "eta":              0.03,
        "subsample":        0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "gamma":            0.1,
        "eval_metric":      "mlogloss",
        "verbosity":        0,
        "seed":             42,
    }
    booster = xgb.train(params, dtrain, num_boost_round=300, verbose_eval=False)

    # ── 5. 피처 중요도 ──────────────────────────────────────────────────
    scores      = booster.get_fscore()   # {f0: score, f1: score, ...}
    total_score = sum(scores.values()) or 1
    importances = [scores.get(f"f{i}", 0) / total_score
                   for i in range(len(feature_names))]

    top10_idx    = np.argsort(importances)[-10:][::-1]
    top_features = [
        {"feature": feature_names[i], "importance": round(float(importances[i]), 4)}
        for i in top10_idx
    ]
    logger.info("[train] 피처 중요도 TOP 10:")
    for item in top_features:
        logger.info(f"  {item['feature']:30s}  {item['importance']:.4f}")

    # ── 6. model/ 저장 ──────────────────────────────────────────────────
    model_path  = MODEL_DIR / 'xgboost_model.json'
    scaler_path = MODEL_DIR / 'scaler.pkl'
    feat_path   = MODEL_DIR / 'feature_list.json'
    label_path  = MODEL_DIR / 'label_config.json'
    report_path = MODEL_DIR / 'train_report.json'

    # XGBoost Booster 저장 (버전 호환 안정적)
    booster.save_model(str(model_path))
    logger.info(f"[save] 모델 저장: {model_path}")

    # 스케일러
    with open(scaler_path, 'wb') as f:
        pickle.dump(scaler, f)
    logger.info(f"[save] 스케일러 저장: {scaler_path}")

    # 피처 목록 (signal.py 가 이 순서로 피처를 읽음)
    with open(feat_path, 'w', encoding='utf-8') as f:
        json.dump(feature_names, f, ensure_ascii=False, indent=2)
    logger.info(f"[save] 피처 목록 저장: {feat_path} ({len(feature_names)}개)")

    # 라벨/임계값 설정
    label_config = {
        "label_map":   {"0": "SELL", "1": "HOLD", "2": "BUY"},
        "target_days": target_days,
        "buy_thr":     buy_thr,
        "sell_thr":    sell_thr,
        "thresholds": {
            "buy_threshold":  pred_thr,
            "sell_threshold": pred_thr,
            "min_volume":     100000,
        },
    }
    with open(label_path, 'w', encoding='utf-8') as f:
        json.dump(label_config, f, ensure_ascii=False, indent=2)
    logger.info(f"[save] 라벨 설정 저장: {label_path}")

    # 학습 리포트
    report = {
        "trained_at":     datetime.now().isoformat(),
        "tickers":        used_tickers,
        "source":         source,
        "total_samples":  int(len(X)),
        "n_features":     int(X.shape[1]),
        "target_days":    target_days,
        "buy_thr":        buy_thr,
        "sell_thr":       sell_thr,
        "pred_threshold": pred_thr,
        "label_dist": {
            "SELL": round(int((y == 0).sum()) / len(y), 4),
            "HOLD": round(int((y == 1).sum()) / len(y), 4),
            "BUY":  round(int((y == 2).sum()) / len(y), 4),
        },
        "cv_accuracy":  cv_result['accuracy'],
        "cv_std":       cv_result['std'],
        "fold_scores":  cv_result['fold_scores'],
        "top_features": top_features,
    }
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"[save] 학습 리포트 저장: {report_path}")

    # ── 7. 최종 요약 ────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("■ 학습 완료")
    logger.info(f"  사용 종목  : {used_tickers}")
    logger.info(f"  전체 샘플  : {len(X):,}개")
    logger.info(f"  피처 수    : {X.shape[1]}개")
    logger.info(f"  CV 정확도  : {cv_result['accuracy']:.3f}±{cv_result['std']:.3f}")
    logger.info(f"  예측 임계값: {pred_thr}")
    logger.info(f"  저장 경로  : {MODEL_DIR}")
    logger.info("=" * 60)
    logger.info("Flask 서버에서 POST /ml/reload 를 호출하면 즉시 반영됩니다.")

    return report


# ═════════════════════════════════════════════════════════════════════════════
# 6. CLI 진입점
# ═════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="XGBoost 주가 방향성 예측 모델 학습",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python train.py
  python train.py --tickers 005930.KS 000660.KS 035720.KS
  python train.py --source yfinance --tickers 005930.KS 000660.KS
  python train.py --target-days 3 --buy-thr 0.02 --sell-thr -0.015
  python train.py --threshold 0.65 --splits 7
        """,
    )
    parser.add_argument('--tickers', nargs='+', default=DEFAULT_TICKERS,
                        help='학습할 종목코드 리스트 (기본: 005930.KS)')
    parser.add_argument('--source', choices=['kiwoom', 'yfinance'],
                        default=DEFAULT_SOURCE,
                        help='데이터 소스 (기본: yfinance)')
    parser.add_argument('--target-days', type=int, default=TARGET_DAYS,
                        help=f'라벨 기준 미래 일수 (기본: {TARGET_DAYS})')
    parser.add_argument('--buy-thr', type=float, default=BUY_THRESHOLD,
                        help=f'매수 라벨 기준 수익률 (기본: {BUY_THRESHOLD})')
    parser.add_argument('--sell-thr', type=float, default=SELL_THRESHOLD,
                        help=f'매도 라벨 기준 수익률 (기본: {SELL_THRESHOLD})')
    parser.add_argument('--threshold', type=float, default=0.60,
                        help='예측 확률 임계값 (기본: 0.60)')
    parser.add_argument('--splits', type=int, default=5,
                        help='Walk-forward fold 수 (기본: 5)')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    logger.info("=" * 60)
    logger.info("■ XGBoost 학습 시작")
    logger.info(f"  종목      : {args.tickers}")
    logger.info(f"  데이터    : {args.source}")
    logger.info(f"  미래 일수 : {args.target_days}일")
    logger.info(f"  매수 기준 : +{args.buy_thr * 100:.1f}%")
    logger.info(f"  매도 기준 : {args.sell_thr * 100:.1f}%")
    logger.info(f"  임계값    : {args.threshold}")
    logger.info("=" * 60)

    train_and_save(
        tickers=args.tickers,
        source=args.source,
        target_days=args.target_days,
        buy_thr=args.buy_thr,
        sell_thr=args.sell_thr,
        pred_thr=args.threshold,
        n_splits=args.splits,
    )