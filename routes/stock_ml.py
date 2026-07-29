"""
routes/stock_ml.py
──────────────────────────────────────────────────────────────────────────────
주가 방향성 예측 라우터.

■ 모델 전략 (32비트 Python 환경 고려)
  Primary  : XGBoost_v2 앙상블 (trading/signal.py) — 64비트 환경에서 동작
  Fallback : LogisticRegressionNumpy — numpy only, 항상 동작 (32비트 완전 호환)

  _predict_xgb() 가 먼저 시도하고, 실패(모델 없음·OHLCV 부족)하면 LR 로 떨어진다.
  2026-07-17 이전에는 trading/signal.py 에 predict 가 없어(파일 내용이 학습 스크립트였다)
  XGBoost 경로가 항상 ImportError 로 죽고 LR 만 동작했다.

■ 데이터 소스
  Primary  : kiwoom_worker.get_ohlcv() — 키움 로그인 시 실시간 일봉
  Fallback : yfinance — 키움 미로그인 시 해외/테스트용
  XGBoost 경로는 XGBoost_v2/data/ohlcv/*.parquet (수집기가 적재) 를 쓴다.

■ 피처셋
  XGBoost : XGBoost_v2/feature_v2.py 82개 (signal.py 가 호출)
  LR      : _compute_features() — numpy only 기술적 지표
  디버깅  : trading.feature.build_features() 34개 — GET /ml/features 의 비교용.
            v1 계보라 XGBoost_v2 모델(82개)과 호환되지 않는다(교집합 16개).

■ signal 어휘 — 두 경로 모두 BUY/SELL/HOLD (프론트 ML_META 키와 일치)
  XGBoost : BUY/HOLD 만. 라벨이 "N일 내 목표수익 달성 AND 낙폭 제한" 이라 여집합에
            횡보가 섞여 매도 근거가 없다(trading/signal.py 참고).
  LR      : BUY/SELL/HOLD. 라벨이 "5일 후 상승 vs 하락" 대칭이라 매도가 성립한다.
            임계값 LR_BUY_PROB/LR_SELL_PROB (기본 0.60, 사이는 HOLD).

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
import os
from datetime import datetime
from functools import lru_cache
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

# LR 폴백의 BUY/SELL 임계값 — trading/trader.py RiskConfig 및 trading/signal.py 와
# 같은 env 키·기본값을 쓴다(레포 단일 규약). 사이 구간은 HOLD.
# 잘못된 값이면 import 가 죽어 라우터 전체가 사라지므로 기본값으로 되돌린다.
def _env_prob(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == '':
        return default
    try:
        v = float(raw)
    except ValueError:
        logger.warning(f'[stock_ml] {key}={raw!r} 를 실수로 읽을 수 없음 → 기본값 {default}')
        return default
    if not 0.0 < v < 1.0:
        logger.warning(f'[stock_ml] {key}={v} 가 (0,1) 밖 → 기본값 {default}')
        return default
    return v


LR_BUY_PROB  = _env_prob('MIN_BUY_PROB',  0.60)
LR_SELL_PROB = _env_prob('MIN_SELL_PROB', 0.60)

# LR 모델이 신호를 낼 자격 — 실측(2026-07-17, KOSPI 표본 8종목) 근거:
#   퇴화 2/8 : baseline≈0 (검증 구간에 상승 사례가 없어 "항상 하락"만 찍고 acc=1.0)
#   무실력 5/8: lift≤0.02, 그중 4개는 음수(-0.08~-0.04) = 다수 클래스 찍기보다 못함
#   실실력 1/8
# parquet 없는 400종목은 대부분 ETF 라, 5일 방향을 기술적 지표로 맞추는 모델에
# 실력이 없다. 자격 미달 모델의 BUY/SELL 은 노이즈를 신호로 승격시키므로 HOLD 로 낮춘다.
# (trading/signal.py 에서 매도 라벨 없는 모델의 SELL 을 뺀 것과 같은 원칙.)
LR_MIN_LIFT = _env_prob('LR_MIN_LIFT', 0.02)          # baseline 대비 최소 개선폭
_LR_DEGENERATE_BASELINE = 0.05                        # baseline 이 이 밖이면 한쪽 클래스뿐

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
            logger.info(f"[ML] 캐시 로드: {len(_MODEL_CACHE)}개 종목")
        except Exception as e:
            logger.error(f"[ML] 캐시 로드 실패: {e}")
            _MODEL_CACHE = {}


def _save_cache_file():
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock:
            with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(_MODEL_CACHE, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[ML] 캐시 저장 실패: {e}")


_load_cache_file()


def _get_ohlcv(code: str, ticker_yfin: str = "", count: int = 500):
    try:
        from kiwoom_client import kiwoom
        if kiwoom.market_data_ready():
            df = kiwoom.get_ohlcv(code, count=count)
            if df is not None and not df.empty and len(df) >= 60:
                return (
                    df["close"].values.astype(float),
                    df["high"].values.astype(float),
                    df["low"].values.astype(float),
                    df["volume"].values.astype(float),
                )
    except Exception as e:
        logger.error(f"[ML] kiwoom OHLCV 실패 ({code}): {e}")

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
        logger.error(f"[ML] yfinance 폴백 실패 ({code}): {e}")

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
    logger.info(f"[ML] {code} 학습 시작...")

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

    logger.info(
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
    """
    LR 폴백 예측. signal 은 BUY/SELL/HOLD 로 낸다.

    2026-07-17 이전에는 '상승'/'하락' 을 반환했는데, 프론트는 BUY/SELL/HOLD 만 안다:
      - StockDetail.jsx:44  `ML_META[signal] || ML_META.HOLD` → 한글 키가 없으니
        상승 확률 83% 종목이 조용히 **"관망"** 으로 표시됐다(오표시, 무증상).
      - CompanyResearch.jsx:64 `[sig] || {label: sig}` → 원문 노출 + 회색 처리.
    XGBoost 경로(trading/signal.py)와 어휘를 통일한다.

    ■ 왜 여기서는 SELL 을 내는가 (trading/signal.py 는 안 내는데)
      LR 라벨은 _train_model 의 `target = (5일 후 수익률 > 0)` — **대칭 방향 라벨**이라
      P(하락) = 1 - P(상승) 이 그대로 성립한다. 반면 XGBoost_v2 라벨은 "N일 내 목표수익
      달성 AND 낙폭 제한" 이라 여집합에 횡보·목표미달이 섞여 매도 근거가 되지 못한다.
    """
    X, _ = _compute_features(close, high, low, volume)
    last = X[-1:]
    prob_up   = float(model.predict_proba(last)[0, 1])
    prob_down = 1.0 - prob_up

    # 이진 예측(prob>=0.5)을 그대로 매핑하면 51% 도 BUY 가 된다. 관망 구간을 둔다.
    if prob_up >= LR_BUY_PROB:
        signal = 'BUY'
    elif prob_down >= LR_SELL_PROB:
        signal = 'SELL'
    else:
        signal = 'HOLD'

    return {
        'prob_up':    round(prob_up * 100, 1),
        'prob_down':  round(prob_down * 100, 1),
        'signal':     signal,
        'confidence': round(prob_up, 4),
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


_DERIV_CACHE_FILE = (Path(__file__).parent.parent / 'XGBoost_v2' / 'data'
                     / 'cache' / 'derivative_codes.json')
_DERIV_TTL_DAYS = 7          # 상장·폐지가 잦지 않아 주 단위면 충분


def _fetch_derivative_codes() -> set:
    """pykrx 에서 ETF/ETN/ELW 코드를 받아온다. 실패하면 빈 집합."""
    codes: set = set()
    try:
        from pykrx import stock as pystock
    except ImportError:
        logger.warning('[stock_ml] pykrx 없음 — ETF/ETN 목록 조회 불가')
        return codes
    for fn in ('get_etf_ticker_list', 'get_etn_ticker_list', 'get_elw_ticker_list'):
        try:
            codes |= set(getattr(pystock, fn)())
        except Exception as e:
            # KRX 가 간헐적으로 비-JSON 을 반환하면 pykrx 내부에서 IndexError 가 난다.
            logger.warning(f'[stock_ml] {fn} 실패: {type(e).__name__}: {e}')
    return codes


@lru_cache(maxsize=2)
def _derivative_codes(day: str) -> frozenset:
    """
    ETF/ETN/ELW 코드 집합. day 는 날짜별 in-process 캐시 무효화 키(값은 안 씀).

    ■ 왜 파일 캐시인가
      요청 시점에 KRX 를 직접 조회하면 KRX 가 흔들릴 때마다(실측: 비-JSON 응답 →
      pykrx 내부 IndexError) 판정이 빈 집합이 되어, **같은 ETF 가 어떤 날은 차단되고
      어떤 날은 예측을 받는 비결정적 동작**이 된다. 한 번 받아 파일에 두고 재사용한다.

    ■ 실패 시 정책
      신선한 파일 → 사용. 조회 성공 → 갱신 후 사용. 조회 실패 → **낡은 파일이라도 사용**.
      아무것도 없으면 빈 집합 = fail-open(예측을 막지 않는다). KRX 장애가 곧 전 종목
      예측 중단이 되면 안 되고, 뒤는 실력 게이트가 받친다.
    """
    cached, stale = None, False
    try:
        if _DERIV_CACHE_FILE.exists():
            payload = json.loads(_DERIV_CACHE_FILE.read_text(encoding='utf-8'))
            cached = set(payload.get('codes', []))
            fetched = datetime.fromisoformat(payload['fetched_at'])
            stale = (datetime.now() - fetched).days >= _DERIV_TTL_DAYS
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f'[stock_ml] 파생상품 캐시 읽기 실패: {e}')

    if cached and not stale:
        return frozenset(cached)

    fresh = _fetch_derivative_codes()
    if fresh:
        try:
            _DERIV_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DERIV_CACHE_FILE.write_text(json.dumps(
                {'fetched_at': datetime.now().isoformat(), 'codes': sorted(fresh)},
                ensure_ascii=False), encoding='utf-8')
        except OSError as e:
            logger.warning(f'[stock_ml] 파생상품 캐시 저장 실패: {e}')
        logger.info(f'[stock_ml] ETF/ETN/ELW {len(fresh)}개 갱신 ({day})')
        return frozenset(fresh)

    if cached:
        logger.warning(f'[stock_ml] KRX 조회 실패 — 낡은 캐시 {len(cached)}개 사용')
        return frozenset(cached)

    logger.warning('[stock_ml] 파생상품 목록 없음 — ETF/ETN 판정을 건너뛴다(예측 진행)')
    return frozenset()


def _is_derivative(code: str, day: str) -> bool:
    """
    ETF/ETN/ELW 인가.

    실측(2026-07-17): KODEX 200 은 정적 피처 35개 중 26개(74%)가 0이다(삼성전자는 2개).
    pykrx 가 ETF 에 get_stock_ticker_isin / get_market_fundamental_by_date 부터 실패한다
    — 재무제표가 없는 상품이라 PER·ROE·부채비율이 존재하지 않기 때문이다.
    그 상태로 예측하면 293개 일반주로 학습한 모델에 0을 26개 먹이는 분포 밖 추론이 된다.
    로컬 parquet 이 없는 411종목 중 397개(97%)가 여기 해당한다.
    """
    return code in _derivative_codes(day)


def _gate_lr_signal(result: dict) -> dict:
    """
    실력이 측정되지 않은 LR 모델의 BUY/SELL 을 HOLD 로 낮춘다.

    왜 필요한가: _predict_lr 은 prob_up 만 보고 임계값을 건다. 그런데 모델 자체가
    베이스라인 이하이거나(lift≤0) 검증 구간이 한쪽 클래스뿐이면(baseline≈0/1),
    그 prob_up 은 근거가 없다. 화면에 "매수 83%"로 뜨면 사용자는 실행 가능한
    신호로 읽는다. 자격 미달이면 관망으로 낮추고 이유를 함께 싣는다.
    """
    if result.get('signal') not in ('BUY', 'SELL'):
        return result

    lift     = result.get('lift')
    baseline = result.get('baseline')
    reason = None

    if baseline is not None and (baseline <= _LR_DEGENERATE_BASELINE
                                 or baseline >= 1.0 - _LR_DEGENERATE_BASELINE):
        reason = (f'검증 구간이 한쪽 클래스뿐(baseline={baseline:.1%}) — '
                  f'모델이 방향을 학습하지 못함')
    elif lift is not None and lift < LR_MIN_LIFT:
        reason = (f'베이스라인 대비 개선 {lift:+.1%} < 기준 {LR_MIN_LIFT:.0%} — '
                  f'실력이 확인되지 않음')

    if reason is None:
        return result

    downgraded = dict(result)
    downgraded['signal'] = 'HOLD'
    downgraded['signal_downgraded_from'] = result['signal']
    downgraded['signal_note'] = reason
    logger.info(f"[stock_ml] LR 신호 {result['signal']}→HOLD: {reason}")
    return downgraded


def get_ml_prediction(code: str, ticker_yfin: str = "",
                      ticker_name: str = "") -> dict:
    # datetime 은 모듈 레벨 임포트 사용

    today = datetime.now().strftime('%Y-%m-%d')
    name  = ticker_name or code

    cached = _MODEL_CACHE.get(code)
    if cached and cached.get('trained_date') == today:
        logger.info(f"[ML] {code} 캐시 히트")
        return {**cached['result'], 'from_cache': True}

    # ETF·ETN·ELW 는 예측 대상이 아니다 — "실력 미달로 관망" 이 아니라 애초에 대상이
    # 아니라고 말해야 한다. 라우터가 이 error 를 404 로 내보내고 프론트가 그대로 표시한다
    # (StockDetail.jsx:177 → :322). signal 값으로 내면 ML_META 폴백에 걸려 또 "관망"이 된다.
    if _is_derivative(code, today):
        return {'error': 'ETF·ETN·ELW는 AI 예측 대상이 아닙니다 '
                         '(재무·공시 데이터가 없어 모델을 적용할 수 없습니다)'}

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

    # meta 의 lift/baseline 이 있어야 신호 자격을 판정할 수 있으므로 병합 후에 건다.
    result = _gate_lr_signal({**pred, **meta_or_err})
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
    # 캐시 엔트리는 {'trained_date', 'result'} 구조다(:578,:598). 예전에는 존재하지
    # 않는 'meta' 키를 읽어 전 필드가 항상 null 이었다. result 에서 읽는다.
    return {
        code: {
            'trained_date': v.get('trained_date'),
            'signal':       v.get('result', {}).get('signal'),
            'confidence':   v.get('result', {}).get('confidence'),
            'model_type':   v.get('result', {}).get('model_type'),
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
