"""
routes/stock_ml.py
──────────────────────────────────────────────────────────────────────────────
주가 방향성 예측 라우터.

■ 모델 전략 (32비트 Python 환경 고려)
  Primary  : LogisticRegressionNumpy — numpy only, 항상 동작 (32비트 완전 호환)
  Optional : XGBoost (trading/signal.py) — 64비트 환경 또는 별도 프로세스에서 사용

■ 데이터 소스
  Primary  : kiwoom_worker.get_ohlcv() — 키움 로그인 시 실시간 일봉
  Fallback : yfinance — 키움 미로그인 시 해외/테스트용

■ 피처셋
  Primary  : _compute_features() — numpy only 기술적 지표 (기존 유지)
  Optional : trading.feature.build_features() — 수급/거시/공시/뉴스 포함 풀 피처셋

■ 유지된 기존 라우트 (UI 호환)
  POST /stock/ml/predict       ← 기존 UI 호환
  GET  /stock/ml/cache         ← 캐시 상태
  POST /stock/ml/cache/clear   ← 캐시 초기화

■ 신규 라우트
  GET  /ml/status              ← XGBoost 모델 로드 상태
  POST /ml/reload              ← XGBoost 모델 강제 재로드
  GET  /ml/predict/{ticker}    ← 단일 종목 예측 (XGBoost 우선 → LR 폴백)
  POST /ml/predict/batch       ← 다중 종목 일괄 예측
  GET  /ml/features/{ticker}   ← 피처값 디버깅 (numpy + full 피처셋 비교)
──────────────────────────────────────────────────────────────────────────────
"""

import logging
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from routes.utils import api_require_login, require_login_smart
import json
import threading
from pathlib import Path
import numpy as np

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent.parent / 'XGBoost_v2' / 'model' / 'ml_lr_cache.json'

_MODEL_CACHE: dict = {}
_cache_lock  = threading.Lock()

_batch_lock    = threading.Lock()
_batch_running = False


def _load_cache_file():
    global _MODEL_CACHE
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                _MODEL_CACHE = json.load(f)
            print(f"[ML] 캐시 로드: {len(_MODEL_CACHE)}개 종목")
        except Exception as e:
            print(f"[ML] 캐시 로드 실패: {e}")
            _MODEL_CACHE = {}


def _save_cache_file():
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock:
            with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(_MODEL_CACHE, f, ensure_ascii=False)
    except Exception as e:
        print(f"[ML] 캐시 저장 실패: {e}")


_load_cache_file()


def _get_ohlcv(code: str, ticker_yfin: str = "", count: int = 500):
    try:
        from kiwoom_client import kiwoom
        if kiwoom.get_login_state() == 1:
            df = kiwoom.get_ohlcv(code, count=count)
            if df is not None and not df.empty and len(df) >= 60:
                return (
                    df["close"].values.astype(float),
                    df["high"].values.astype(float),
                    df["low"].values.astype(float),
                    df["volume"].values.astype(float),
                )
    except Exception as e:
        print(f"[ML] kiwoom OHLCV 실패 ({code}): {e}")

    try:
        import yfinance as yf
        from datetime import datetime, timedelta
        end    = datetime.now()
        start  = end - timedelta(days=int(count * 1.5))
        yfcode = ticker_yfin or (code + ".KS")
        df     = yf.Ticker(yfcode).history(start=start, end=end)
        if df is not None and not df.empty and len(df) >= 60:
            return (
                df["Close"].values.astype(float),
                df["High"].values.astype(float),
                df["Low"].values.astype(float),
                df["Volume"].values.astype(float),
            )
    except Exception as e:
        print(f"[ML] yfinance 폴백 실패 ({code}): {e}")

    return None, None, None, None


def _compute_features(close, high, low, volume):
    n = len(close)

    def rolling_mean(arr, w):
        result = np.full(n, np.nan)
        for i in range(w - 1, n):
            result[i] = np.mean(arr[i - w + 1:i + 1])
        return result

    def rolling_std(arr, w):
        result = np.full(n, np.nan)
        for i in range(w - 1, n):
            result[i] = np.std(arr[i - w + 1:i + 1], ddof=0)
        return result

    feats = {}

    for w in [5, 10, 20, 60]:
        ma = rolling_mean(close, w)
        with np.errstate(divide='ignore', invalid='ignore'):
            feats[f'ma{w}_gap'] = np.where(ma > 0, close / ma - 1, 0)

    delta    = np.diff(close, prepend=close[0])
    gain     = np.where(delta > 0, delta, 0.0)
    loss     = np.where(delta < 0, -delta, 0.0)
    avg_gain = rolling_mean(gain, 14)
    avg_loss = rolling_mean(loss, 14)
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
    feats['rsi'] = 100 - 100 / (1 + rs)

    def ema(arr, span):
        k      = 2 / (span + 1)
        result = np.full(n, np.nan)
        result[0] = arr[0]
        for i in range(1, n):
            result[i] = arr[i] * k + result[i - 1] * (1 - k)
        return result

    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    macd  = ema12 - ema26
    sig   = ema(macd, 9)
    feats['macd_hist']  = macd - sig
    feats['macd_cross'] = (macd > sig).astype(float)

    ma20  = rolling_mean(close, 20)
    std20 = rolling_std(close, 20)
    bb_range = 4 * std20
    with np.errstate(divide='ignore', invalid='ignore'):
        feats['bb_pos'] = np.where(
            bb_range > 0,
            (close - (ma20 - 2 * std20)) / bb_range,
            0.5,
        )

    vol_ma5  = rolling_mean(volume, 5)
    vol_ma20 = rolling_mean(volume, 20)
    with np.errstate(divide='ignore', invalid='ignore'):
        feats['vol_ratio_5']  = np.where(vol_ma5  > 0, volume / vol_ma5,  1.0)
        feats['vol_ratio_20'] = np.where(vol_ma20 > 0, volume / vol_ma20, 1.0)

    prev_close    = np.roll(close, 1)
    prev_close[0] = close[0]
    tr    = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low  - prev_close),
    ])
    atr14 = rolling_mean(tr, 14)
    with np.errstate(divide='ignore', invalid='ignore'):
        feats['atr_ratio'] = np.where(close > 0, atr14 / close, 0)

    for d in [1, 3, 5, 10, 20]:
        shifted = np.roll(close, d)
        shifted[:d] = close[:d]
        with np.errstate(divide='ignore', invalid='ignore'):
            feats[f'ret_{d}d'] = np.where(shifted > 0, close / shifted - 1, 0)

    hi20  = np.array([np.max(high[max(0, i - 20):i + 1]) for i in range(n)])
    lo20  = np.array([np.min(low[max(0,  i - 20):i + 1]) for i in range(n)])
    rng20 = hi20 - lo20
    with np.errstate(divide='ignore', invalid='ignore'):
        feats['chan_pos'] = np.where(rng20 > 0, (close - lo20) / rng20, 0.5)

    feat_names = list(feats.keys())
    X = np.column_stack([feats[k] for k in feat_names])
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    X = np.clip(X, -10, 10)

    return X, feat_names


class LogisticRegressionNumpy:
    def __init__(self, lr=0.01, n_iter=500, C=1.0):
        self.lr     = lr
        self.n_iter = n_iter
        self.C      = C
        self.w      = None
        self.b      = 0.0
        self.mu     = None
        self.sigma  = None

    def _sigmoid(self, z):
        return 1 / (1 + np.exp(-np.clip(z, -500, 500)))

    def _normalize(self, X, fit=False):
        if fit:
            self.mu    = X.mean(axis=0)
            self.sigma = X.std(axis=0) + 1e-8
        return (X - self.mu) / self.sigma

    def fit(self, X, y):
        Xn   = self._normalize(X, fit=True)
        m, d = Xn.shape
        self.w = np.zeros(d)
        self.b = 0.0
        for _ in range(self.n_iter):
            z      = Xn @ self.w + self.b
            p      = self._sigmoid(z)
            err    = p - y
            grad_w = (Xn.T @ err) / m + (1 / self.C) * self.w
            grad_b = err.mean()
            self.w -= self.lr * grad_w
            self.b -= self.lr * grad_b
        return self

    def predict_proba(self, X):
        Xn = self._normalize(X)
        z  = Xn @ self.w + self.b
        p1 = self._sigmoid(z)
        return np.column_stack([1 - p1, p1])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    @property
    def feature_importances_(self):
        w_abs = np.abs(self.w)
        return w_abs / (w_abs.sum() + 1e-9)


def _train_model(code: str, ticker_yfin: str = ""):
    print(f"[ML] {code} 학습 시작...")

    close, high, low, volume = _get_ohlcv(code, ticker_yfin, count=500)

    if close is None or len(close) < 120:
        n = len(close) if close is not None else 0
        return None, f"데이터 부족 ({n}일) — 키움 로그인 또는 ticker 확인"

    X, feat_names = _compute_features(close, high, low, volume)

    TARGET_DAYS = 5
    future_ret  = np.zeros(len(close))
    for i in range(len(close) - TARGET_DAYS):
        future_ret[i] = (close[i + TARGET_DAYS] - close[i]) / close[i]
    target = (future_ret > 0).astype(int)

    valid              = np.ones(len(close), dtype=bool)
    valid[:60]         = False
    valid[-TARGET_DAYS:] = False
    X_v = X[valid]
    y_v = target[valid]

    if len(X_v) < 80:
        return None, f"유효 샘플 부족 ({len(X_v)}개)"

    n_splits  = 5
    fold_size = len(X_v) // n_splits
    cv_scores = []

    for fold in range(n_splits):
        val_start = fold * fold_size
        val_end   = val_start + fold_size
        train_end = val_start

        if train_end < 30:
            continue

        X_tr  = X_v[:train_end]
        y_tr  = y_v[:train_end]
        X_val = X_v[val_start:val_end]
        y_val = y_v[val_start:val_end]

        if len(X_tr) < 20 or len(X_val) < 10:
            continue

        m   = LogisticRegressionNumpy(lr=0.01, n_iter=300, C=1.0)
        m.fit(X_tr, y_tr)
        acc = float((m.predict(X_val) == y_val).mean())
        cv_scores.append(acc)

    if not cv_scores:
        return None, "교차검증 샘플 부족"

    final_model = LogisticRegressionNumpy(lr=0.01, n_iter=500, C=1.0)
    final_model.fit(X_v, y_v)

    cv_acc   = float(np.mean(cv_scores))
    cv_std   = float(np.std(cv_scores))
    baseline = float(y_v.mean())

    importances  = final_model.feature_importances_
    top5_idx     = importances.argsort()[-5:][::-1]
    top_features = [(feat_names[i], round(float(importances[i]), 4))
                    for i in top5_idx]

    print(
        f"[ML] {code} 완료 | "
        f"정확도: {cv_acc:.3f}±{cv_std:.3f} | "
        f"기준선: {baseline:.3f} | "
        f"향상: +{cv_acc - baseline:.3f}"
    )

    meta = {
        'cv_accuracy':   round(cv_acc,   4),
        'cv_std':        round(cv_std,   4),
        'baseline':      round(baseline, 4),
        'lift':          round(cv_acc - baseline, 4),
        'top_features':  top_features,
        'sample_size':   len(X_v),
        'feature_names': feat_names,
        'model_type':    'LogisticRegressionNumpy',
    }
    return final_model, meta


def _predict_lr(model: LogisticRegressionNumpy,
                close, high, low, volume) -> dict:
    X, _ = _compute_features(close, high, low, volume)
    last  = X[-1:]
    prob  = float(model.predict_proba(last)[0, 1])
    pred  = int(model.predict(last)[0])
    return {
        'prob_up':    round(prob * 100, 1),
        'prob_down':  round((1 - prob) * 100, 1),
        'signal':     '상승' if pred == 1 else '하락',
        'model_type': 'LogisticRegressionNumpy',
    }


def _predict_xgb(ticker: str, ticker_name: str,
                 ohlcv_df=None) -> dict | None:
    try:
        from trading.signal import predict as sig_predict
        result = sig_predict(ticker, ticker_name, ohlcv_df)
        if result.get('signal') == 'ERROR':
            return None
        return result
    except Exception:
        return None


def get_ml_prediction(code: str, ticker_yfin: str = "",
                      ticker_name: str = "") -> dict:
    from datetime import datetime

    today = datetime.now().strftime('%Y-%m-%d')
    name  = ticker_name or code

    cached = _MODEL_CACHE.get(code)
    if cached and cached.get('trained_date') == today:
        print(f"[ML] {code} 캐시 히트")
        return {**cached['result'], 'from_cache': True}

    xgb_result = _predict_xgb(code, name)
    if xgb_result:
        with _cache_lock:
            _MODEL_CACHE[code] = {'trained_date': today, 'result': xgb_result}
        _save_cache_file()
        return {**xgb_result, 'from_cache': False}

    close, high, low, volume = _get_ohlcv(code, ticker_yfin, count=120)
    if close is None:
        return {'error': 'OHLCV 조회 실패 — 키움 로그인 또는 종목코드 확인'}

    model, meta_or_err = _train_model(code, ticker_yfin)
    if model is None:
        return {'error': meta_or_err}

    try:
        pred = _predict_lr(model, close, high, low, volume)
    except Exception as e:
        return {'error': f"예측 오류: {e}"}

    result = {**pred, **meta_or_err}
    with _cache_lock:
        _MODEL_CACHE[code] = {'trained_date': today, 'result': result}
    _save_cache_file()
    return {**result, 'from_cache': False}


@router.post('/stock/ml/predict', dependencies=[Depends(api_require_login)])
def ml_predict_legacy(request: Request, data: dict = Body(default={})):
    code        = data.get('code',   '').strip()
    ticker_yfin = data.get('ticker', code + '.KS').strip()
    ticker_name = data.get('name',   code).strip()

    if not code:
        return JSONResponse({"error": "code 필요"}, status_code=400)

    return get_ml_prediction(code, ticker_yfin, ticker_name)


@router.get('/stock/ml/cache')
def ml_cache_status():
    return {
        code: {
            'trained_date': v.get('trained_date'),
            'cv_accuracy':  v.get('meta', {}).get('cv_accuracy'),
            'sample_size':  v.get('meta', {}).get('sample_size'),
            'model_type':   v.get('meta', {}).get('model_type'),
        }
        for code, v in _MODEL_CACHE.items()
    }


@router.post('/stock/ml/cache/clear')
def ml_cache_clear():
    with _cache_lock:
        _MODEL_CACHE.clear()
    if _CACHE_FILE.exists():
        _CACHE_FILE.unlink()
    return {"status": "ok", "message": "캐시 초기화 완료"}


@router.get('/ml/status')
def ml_status():
    xgb_available = False
    xgb_status    = {}
    try:
        from trading.signal import get_model_status
        xgb_status    = get_model_status()
        xgb_available = True
    except Exception:
        pass

    return {
        "ok":             True,
        "xgb_available":  xgb_available,
        "lr_cache_count": len(_MODEL_CACHE),
        **xgb_status,
    }


@router.post('/ml/reload')
def ml_reload():
    try:
        from XGBoost_v2.daily_recommend import reload_ensemble
        reload_ensemble()
    except Exception:
        pass

    try:
        from trading.signal import reload_model
        success = reload_model()
        with _cache_lock:
            _MODEL_CACHE.clear()
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
        if success:
            return {"ok": True, "message": "앙상블·XGBoost 재로드 + LR 캐시 초기화 완료"}
        return JSONResponse({"ok": False, "error": "XGBoost 재로드 실패 — model/ 파일 확인"}, status_code=500)
    except ImportError:
        with _cache_lock:
            _MODEL_CACHE.clear()
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
        return {"ok": True, "message": "LR 캐시 초기화 완료 (XGBoost 미설치)"}
    except Exception as e:
        logger.error(f'[stock_ml] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/ml/predict/{ticker}')
def ml_predict_get(ticker: str, request: Request):
    try:
        ticker      = ticker.strip().lstrip('A')
        ticker_name = request.query_params.get('name', ticker).strip()

        result = get_ml_prediction(ticker, ticker + ".KS", ticker_name)
        if 'error' in result:
            return JSONResponse({"ok": False, **result}, status_code=404)

        return {"ok": True, "ticker": ticker, **result}

    except Exception as e:
        logger.error(f'[stock_ml] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.post('/ml/predict/batch')
def ml_predict_batch(request: Request, body: dict = Body(default={})):
    global _batch_running

    try:
        with _batch_lock:
            if _batch_running:
                return JSONResponse({"ok": False, "error": "배치 예측 실행 중. 잠시 후 재시도"}, status_code=429)
            _batch_running = True

        try:
            raw_tickers = body.get('tickers', [])
            filter_sig  = body.get('filter', None)

            if not raw_tickers:
                return JSONResponse({"ok": False, "error": "tickers 배열 필요"}, status_code=400)
            if len(raw_tickers) > 20:
                return JSONResponse({"ok": False, "error": "최대 20개까지 가능"}, status_code=400)

            results = []
            for t in raw_tickers:
                code   = t.get('ticker', '').strip().lstrip('A')
                name   = t.get('name', code).strip()
                if not code:
                    continue

                result = get_ml_prediction(code, code + ".KS", name)
                if 'error' in result:
                    continue
                if filter_sig and result.get('signal') != filter_sig:
                    continue

                results.append({"ticker": code, **result})

            results.sort(
                key=lambda r: r.get('confidence', r.get('prob_up', 0) / 100),
                reverse=True,
            )

            return {"ok": True, "count": len(results), "results": results}

        finally:
            with _batch_lock:
                _batch_running = False

    except Exception as e:
        with _batch_lock:
            _batch_running = False
        logger.error(f'[stock_ml] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/ml/features/{ticker}')
def ml_features(ticker: str, request: Request):
    try:
        ticker      = ticker.strip().lstrip('A')
        ticker_name = request.query_params.get('name', ticker).strip()

        close, high, low, volume = _get_ohlcv(ticker, ticker + ".KS", count=80)
        if close is None:
            return JSONResponse({"ok": False, "error": "OHLCV 없음"}, status_code=404)

        X, feat_names = _compute_features(close, high, low, volume)
        last_row      = X[-1]
        numpy_feats   = {feat_names[i]: round(float(last_row[i]), 6)
                         for i in range(len(feat_names))}

        response = {
            "ok":             True,
            "ticker":         ticker,
            "name":           ticker_name,
            "price":          float(close[-1]),
            "ohlcv_rows":     len(close),
            "numpy_features": numpy_feats,
            "full_features":  None,
        }

        try:
            import pandas as pd
            from trading.feature import build_features
            df = pd.DataFrame({
                "open":   close,
                "high":   high,
                "low":    low,
                "close":  close,
                "volume": volume,
            })
            full = build_features(ticker, ticker_name, df)
            response["full_features"] = {k: round(v, 6) for k, v in full.items()}
        except Exception as e:
            response["full_features_error"] = type(e).__name__

        return response

    except Exception as e:
        logger.error(f'[stock_ml] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)
