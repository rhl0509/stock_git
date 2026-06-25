"""
XGBoost_v2/quant_gate.py
=========================
퀀트 신호 유틸리티 (feature_v2 및 daily_recommend에서 공용).

routes/quant.py의 핵심 신호 로직을 분리 — 패키지 간 순환 의존성 없음.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _norm_series(s: pd.Series, window: int = 60) -> pd.Series:
    mu  = s.rolling(window, min_periods=1).mean()
    std = s.rolling(window, min_periods=1).std().replace(0, 1)
    return (s - mu) / (std + 1e-9)


def compute_hurst(series: pd.Series, max_lag: int = 40) -> float:
    """
    R/S 분석으로 Hurst 지수 계산.
    H > 0.6 = 추세 지속, H ≈ 0.5 = 랜덤워크, H < 0.4 = 평균회귀.
    데이터 부족 시 0.5(랜덤워크) 반환.
    """
    s = series.dropna().values
    n = len(s)
    if n < max_lag * 2:
        return 0.5

    lags    = range(2, min(max_lag, n // 2))
    rs_vals = []
    for lag in lags:
        chunks   = [s[i:i + lag] for i in range(0, n - lag + 1, lag)]
        rs_chunk = []
        for chunk in chunks:
            if len(chunk) < 4:
                continue
            m   = np.mean(chunk)
            dev = np.cumsum(chunk - m)
            r   = dev.max() - dev.min()
            sd  = np.std(chunk, ddof=1)
            if sd > 0:
                rs_chunk.append(r / sd)
        rs_vals.append(np.mean(rs_chunk) if rs_chunk else 1.0)

    if len(rs_vals) < 2:
        return 0.5

    log_lags = np.log(list(lags))
    log_rs   = np.log(np.clip(rs_vals, 1e-9, None))
    try:
        h = float(np.polyfit(log_lags, log_rs, 1)[0])
    except Exception:
        h = 0.5
    return float(np.clip(h, 0.0, 1.0))


def compute_regime(c: pd.Series) -> tuple[int, int, int]:
    """
    마지막 행 기준 시장 체제 반환: (trend_bull, vol_low, regime 0-3).
    regime 3 = 강세+저변동 (최적 매수), 0 = 약세+고변동 (최악).
    """
    ma200      = c.rolling(200, min_periods=60).mean()
    vol20      = c.pct_change().rolling(20).std() * np.sqrt(252)
    vol252     = c.pct_change().rolling(252, min_periods=60).std() * np.sqrt(252)
    trend_bull = int((c > ma200).iloc[-1])
    vol_low    = int((vol20 < vol252 * 1.2).iloc[-1])
    regime     = trend_bull * 2 + vol_low
    return trend_bull, vol_low, regime


def compute_composite_signal(df: pd.DataFrame) -> float:
    """
    OHLCV DataFrame의 마지막 행 기준 복합 퀀트 신호 반환.
    양수 강할수록 매수 신호, 음수는 매도 신호.
    데이터 부족(< 60행) 또는 오류 시 0.0 반환.
    """
    try:
        c = df["close"]
        h = df["high"]
        l = df["low"]
        v = df["volume"]

        if len(c) < 60:
            return 0.0

        # RSI 14
        delta = c.diff()
        gain  = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss  = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
        rsi   = 100 - 100 / (1 + gain / (loss + 1e-9))

        # Stochastic K
        stoch_k = 100 * (c - l.rolling(14).min()) / (
            h.rolling(14).max() - l.rolling(14).min() + 1e-9)

        # Bollinger %B
        ma20   = c.rolling(20).mean()
        std20  = c.rolling(20).std()
        bb_pct = (c - (ma20 - 2 * std20)) / (4 * std20 + 1e-9)

        # MACD histogram
        ema12     = c.ewm(span=12, adjust=False).mean()
        ema26     = c.ewm(span=26, adjust=False).mean()
        macd      = ema12 - ema26
        macd_hist = macd - macd.ewm(span=9, adjust=False).mean()

        # Momentum 20d
        mom20 = c.pct_change(20)

        # VWAP deviation (20-day rolling)
        tp       = (h + l + c) / 3
        vwap     = (tp * v).rolling(20).sum() / (v.rolling(20).sum() + 1e-9)
        vwap_dev = (c - vwap) / (vwap + 1e-9)

        # Volume ratio
        vol_ratio = v / (v.rolling(20).mean() + 1e-9)

        # OBV normalized
        obv      = (np.sign(c.diff().fillna(0)) * v).cumsum()
        obv_norm = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-9)

        composite = (
            _norm_series(-rsi)       * 0.15 +
            _norm_series(-stoch_k)   * 0.10 +
            _norm_series(-bb_pct)    * 0.12 +
            _norm_series(macd_hist)  * 0.20 +
            _norm_series(mom20)      * 0.15 +
            _norm_series(-vwap_dev)  * 0.10 +
            _norm_series(vol_ratio)  * 0.08 +
            _norm_series(obv_norm)   * 0.10
        )

        val = float(composite.iloc[-1])
        return val if np.isfinite(val) else 0.0
    except Exception:
        return 0.0
