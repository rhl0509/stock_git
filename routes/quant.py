"""
routes/quant.py — 퀀트 트레이딩 시스템
  1. 신호 생성   (RSI / BB / ATR / MACD / VWAP / StochRSI / OBV + 복합 신호)
  2. 백테스팅    (수수료+세금+슬리피지 / 전 지표 / Monte Carlo / Walk-Forward / 파라미터 최적화)
  3. 포트폴리오  (Max Sharpe / Min Variance / Risk Parity / CVaR 최적화)
  4. 리스크 관리 (VaR / CVaR / Kelly / ATR 사이징 / 변동성 타겟팅 / 스트레스 테스트)
  5. 전략 스캐너 (전 종목 복합 신호 스캔 → 매수/매도 후보 랭킹)
"""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
from fastapi import APIRouter, Request, Depends, Body
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from templates_config import render

router = APIRouter(dependencies=[Depends(require_login_smart)])

OHLCV_DIR    = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ohlcv"
META_JSON    = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ticker_meta.json"

TRADING_DAYS = 252
RF_ANNUAL    = 0.035    # 무위험 수익률 (국고채 3.5%)
BUY_COST     = 0.00015  # 매수 수수료 0.015%
SELL_COST    = 0.00230  # 매도 수수료 + 증권거래세 + 유관기관
SLIPPAGE     = 0.00050  # 시장 충격 슬리피지 0.05%


# ══════════════════════════════════════════════════════════════
# 공통 유틸
# ══════════════════════════════════════════════════════════════

def _load_meta() -> dict:
    try:
        return json.loads(META_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_ohlcv(code: str, lookback: int = 504) -> pd.DataFrame | None:
    p = OHLCV_DIR / f"{code}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().tail(lookback)
    return df if len(df) >= 60 else None


def _load_returns(codes: list, lookback: int = 504) -> pd.DataFrame:
    frames = {}
    for code in codes:
        df = _load_ohlcv(code, lookback)
        if df is not None:
            frames[code] = np.log(df["close"] / df["close"].shift(1)).dropna()
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).dropna()


def _norm_series(s: pd.Series, window: int = 60) -> pd.Series:
    mu = s.rolling(window).mean()
    sd = s.rolling(window).std()
    return (s - mu) / (sd + 1e-9)


# ══════════════════════════════════════════════════════════════
# 수학 모델: Hurst 지수 / 레짐 감지 / VWAP / StochRSI
# ══════════════════════════════════════════════════════════════

def _hurst_exponent(series: np.ndarray, max_lag: int = 40) -> float:
    """
    R/S 분석으로 Hurst 지수 계산.
    H > 0.6 → 추세 지속 (모멘텀 전략 유효)
    H ≈ 0.5 → 랜덤워크
    H < 0.4 → 평균 회귀 (역추세 전략 유효)
    """
    lags    = range(4, min(max_lag, len(series) // 4))
    tau_arr = []
    rs_arr  = []

    for lag in lags:
        rs_vals = []
        for start in range(0, len(series) - lag, lag):
            chunk = series[start : start + lag].astype(float)
            if len(chunk) < 4:
                continue
            mean_c = chunk.mean()
            devs   = np.cumsum(chunk - mean_c)
            R      = devs.max() - devs.min()
            S      = chunk.std(ddof=1)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            tau_arr.append(lag)
            rs_arr.append(np.mean(rs_vals))

    if len(tau_arr) < 4:
        return 0.5

    H, _ = np.polyfit(np.log(tau_arr), np.log(rs_arr), 1)
    return round(float(np.clip(H, 0, 1)), 3)


def _detect_regime(c: pd.Series) -> pd.DataFrame:
    """
    시장 레짐 감지 (추세 × 변동성 2×2 행렬):
      regime 3 = 강세+저변동 (최적 매수)
      regime 2 = 강세+고변동
      regime 1 = 약세+저변동
      regime 0 = 약세+고변동 (최악)
    """
    ma50   = c.rolling(50,  min_periods=20).mean()
    ma200  = c.rolling(200, min_periods=60).mean()
    ret    = c.pct_change()
    vol20  = ret.rolling(20).std()  * np.sqrt(TRADING_DAYS)
    vol252 = ret.rolling(252, min_periods=60).std() * np.sqrt(TRADING_DAYS)

    trend_bull = (c > ma200).astype(int)
    vol_low    = (vol20 < vol252 * 1.2).astype(int)
    regime     = trend_bull * 2 + vol_low

    return pd.DataFrame({
        "ma50":       ma50.round(0),
        "ma200":      ma200.round(0),
        "vol20_ann":  (vol20  * 100).round(2),
        "vol252_ann": (vol252 * 100).round(2),
        "trend_bull": trend_bull,
        "vol_low":    vol_low,
        "regime":     regime,
    }, index=c.index)


def _stoch_rsi(close: pd.Series, rsi_period: int = 14,
               stoch_period: int = 14) -> tuple[pd.Series, pd.Series]:
    """Stochastic RSI (%K, %D). 0-100 스케일."""
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=rsi_period - 1, min_periods=rsi_period).mean()
    loss  = (-delta).clip(lower=0).ewm(com=rsi_period - 1, min_periods=rsi_period).mean()
    rsi   = 100 - 100 / (1 + gain / (loss + 1e-9))

    rsi_min = rsi.rolling(stoch_period).min()
    rsi_max = rsi.rolling(stoch_period).max()
    k = 100 * (rsi - rsi_min) / (rsi_max - rsi_min + 1e-9)
    d = k.rolling(3).mean()
    return k, d


def _vwap_rolling(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling VWAP = Σ(Typical × Volume) / ΣVolume (n일 윈도우)"""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).rolling(window).sum() / df["volume"].rolling(window).sum()


# ══════════════════════════════════════════════════════════════
# 1. 신호 생성
# ══════════════════════════════════════════════════════════════

def _compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    # ── RSI ──
    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss  = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
    rsi   = 100 - 100 / (1 + gain / (loss + 1e-9))

    # ── Stochastic RSI ──
    stoch_k, stoch_d = _stoch_rsi(c)

    # ── Bollinger Bands ──
    ma20     = c.rolling(20).mean()
    std20    = c.rolling(20).std()
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20
    bb_pct   = (c - bb_lower) / (bb_upper - bb_lower + 1e-9)
    bb_width = (bb_upper - bb_lower) / (ma20 + 1e-9) * 100  # 밴드 폭 %

    # ── ATR ──
    tr    = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(span=14, min_periods=14).mean()
    atr_pct = atr14 / c * 100

    # ── MACD ──
    ema12     = c.ewm(span=12, min_periods=12).mean()
    ema26     = c.ewm(span=26, min_periods=26).mean()
    macd      = ema12 - ema26
    macd_sig  = macd.ewm(span=9, min_periods=9).mean()
    macd_hist = macd - macd_sig

    # ── VWAP 이탈도 ──
    vwap    = _vwap_rolling(df, 20)
    vwap_dev = (c - vwap) / (vwap + 1e-9) * 100  # VWAP 대비 %

    # ── 모멘텀 ──
    mom5  = c.pct_change(5)  * 100
    mom20 = c.pct_change(20) * 100
    mom60 = c.pct_change(60) * 100

    # ── 가격 Z-score ──
    z20 = (c - c.rolling(20).mean()) / (c.rolling(20).std() + 1e-9)
    z60 = (c - c.rolling(60).mean()) / (c.rolling(60).std() + 1e-9)

    # ── 거래량 강도 / OBV ──
    vol_ratio = v / (v.rolling(20).mean() + 1e-9)
    obv       = (np.sign(c.diff()) * v).cumsum()
    obv_norm  = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-9)

    # ── 이동평균 ──
    ma50  = c.rolling(50,  min_periods=20).mean()
    ma200 = c.rolling(200, min_periods=60).mean()

    # ── 복합 신호 (가중 Z-score 합산) ──
    composite = (
        _norm_series(-rsi)          * 0.15 +
        _norm_series(-stoch_k)      * 0.10 +
        _norm_series(-bb_pct)       * 0.12 +
        _norm_series(macd_hist)     * 0.20 +
        _norm_series(mom20)         * 0.15 +
        _norm_series(-vwap_dev)     * 0.10 +  # VWAP 아래면 매수 우호
        _norm_series(vol_ratio)     * 0.08 +
        _norm_series(obv_norm)      * 0.10
    )

    return pd.DataFrame({
        "close":     c.round(0),
        "ma50":      ma50.round(0),
        "ma200":     ma200.round(0),
        "rsi":       rsi.round(2),
        "stoch_k":   stoch_k.round(2),
        "stoch_d":   stoch_d.round(2),
        "bb_upper":  bb_upper.round(0),
        "bb_lower":  bb_lower.round(0),
        "bb_pct":    (bb_pct * 100).round(1),
        "bb_width":  bb_width.round(2),
        "atr":       atr14.round(0),
        "atr_pct":   atr_pct.round(2),
        "macd":      macd.round(2),
        "macd_sig":  macd_sig.round(2),
        "macd_hist": macd_hist.round(2),
        "vwap":      vwap.round(0),
        "vwap_dev":  vwap_dev.round(2),
        "z20":       z20.round(3),
        "z60":       z60.round(3),
        "mom5":      mom5.round(2),
        "mom20":     mom20.round(2),
        "mom60":     mom60.round(2),
        "vol_ratio": vol_ratio.round(2),
        "obv_norm":  obv_norm.round(3),
        "composite": composite.round(3),
    }, index=df.index).dropna()


# ══════════════════════════════════════════════════════════════
# 2. 백테스팅
# ══════════════════════════════════════════════════════════════

def _build_entry_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    sig     = pd.Series(False, index=df.index)
    signals = _compute_signals(df).reindex(df.index)
    mode    = params.get("mode", "composite")

    if mode == "composite":
        sig = signals["composite"].fillna(0) >= float(params.get("composite_threshold", 0.5))
    elif mode == "rsi":
        sig = signals["rsi"].fillna(50) < float(params.get("rsi_oversold", 30))
    elif mode == "stoch_rsi":
        k, d = signals["stoch_k"].fillna(50), signals["stoch_d"].fillna(50)
        sig  = (k < 20) & (k > d) & (k.shift(1) <= d.shift(1))  # 과매도 후 %K가 %D 상향 돌파
    elif mode == "macd":
        hist = signals["macd_hist"].fillna(0)
        sig  = (hist > 0) & (hist.shift(1) <= 0)
    elif mode == "bb":
        sig = signals["bb_pct"].fillna(50) < float(params.get("bb_threshold", 20))
    elif mode == "vwap":
        sig = signals["vwap_dev"].fillna(0) < float(params.get("vwap_threshold", -2))
    elif mode == "momentum":
        sig = signals["mom20"].fillna(0) > float(params.get("mom_threshold", 5))

    return sig.fillna(False)


def _simulate(df: pd.DataFrame, signal: pd.Series,
              hold_days: int = 5, stop_pct: float = 0.05,
              target_pct: float = 0.10, capital: float = 10_000_000) -> dict:
    closes = df["close"].values
    opens  = df["open"].values
    dates  = df.index
    n      = len(closes)

    trades   = []
    equity   = [capital]
    cash     = capital
    position = None

    for i in range(1, n):
        exec_price = opens[i]

        if position:
            entry_p   = position["cost"]
            ret       = (exec_price * (1 - SLIPPAGE - SELL_COST) - entry_p) / entry_p
            days_held = i - position["idx"]
            exit_reason = None

            if ret >= target_pct:     exit_reason = "target"
            elif ret <= -stop_pct:    exit_reason = "stop"
            elif days_held >= hold_days: exit_reason = "timeout"

            if exit_reason:
                sell_price = exec_price * (1 - SLIPPAGE - SELL_COST)
                cash      += sell_price * position["shares"]
                ret_pct    = (sell_price - entry_p) / entry_p * 100
                trades.append({
                    "entry_date":  position["date"].strftime("%Y-%m-%d"),
                    "exit_date":   dates[i].strftime("%Y-%m-%d"),
                    "entry_price": int(position["raw_entry"]),
                    "exit_price":  int(exec_price),
                    "return_pct":  round(ret_pct, 2),
                    "exit_reason": exit_reason,
                    "days_held":   days_held,
                })
                equity.append(round(cash))
                position = None

        if position is None and signal.iloc[i - 1] and i + 1 < n:
            buy_price = exec_price * (1 + SLIPPAGE + BUY_COST)
            shares    = int(cash * 0.95 / buy_price)
            if shares > 0:
                cash    -= buy_price * shares
                position = {"cost": buy_price, "raw_entry": exec_price,
                            "date": dates[i], "idx": i, "shares": shares}

    if position:
        sell_price = closes[-1] * (1 - SLIPPAGE - SELL_COST)
        cash      += sell_price * position["shares"]
        ret_pct    = (sell_price - position["cost"]) / position["cost"] * 100
        trades.append({
            "entry_date":  position["date"].strftime("%Y-%m-%d"),
            "exit_date":   dates[-1].strftime("%Y-%m-%d"),
            "entry_price": int(position["raw_entry"]),
            "exit_price":  int(closes[-1]),
            "return_pct":  round(ret_pct, 2),
            "exit_reason": "force",
            "days_held":   n - 1 - position["idx"],
        })
        equity.append(round(cash))

    return {"trades": trades, "equity": equity}


def _compute_full_metrics(trades: list, equity: list, bh_ret: float) -> dict:
    if not trades or len(equity) < 2:
        return {}

    rets      = np.array([t["return_pct"] / 100 for t in trades])
    eq        = np.array(equity)
    total_ret = (eq[-1] - eq[0]) / eq[0]
    n_trades  = len(trades)

    wins          = rets[rets > 0]
    losses        = rets[rets < 0]
    win_rate      = len(wins) / n_trades if n_trades else 0
    avg_win       = float(wins.mean())   if len(wins)   else 0.0
    avg_loss      = float(losses.mean()) if len(losses) else 0.0
    profit_factor = (wins.sum() / (-losses.sum())) if losses.sum() < 0 else 999.0
    expectancy    = win_rate * avg_win + (1 - win_rate) * avg_loss

    hold_days_total = sum(t["days_held"] for t in trades)
    years  = max(hold_days_total / TRADING_DAYS, 1 / TRADING_DAYS)
    cagr   = (eq[-1] / eq[0]) ** (1 / years) - 1

    annual_vol = float(rets.std() * np.sqrt(TRADING_DAYS)) if len(rets) > 1 else 0.0
    sharpe     = (cagr - RF_ANNUAL) / annual_vol if annual_vol > 0 else 0.0

    down_vol = float(losses.std() * np.sqrt(TRADING_DAYS)) if len(losses) > 1 else 1e-9
    sortino  = (cagr - RF_ANNUAL) / down_vol if down_vol > 0 else 0.0

    peak   = np.maximum.accumulate(eq)
    dd     = (eq - peak) / peak
    max_dd = float(dd.min())
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    var_95 = float(np.percentile(rets, 5)) * 100 if len(rets) >= 5 else 0.0

    return {
        "n_trades":      n_trades,
        "win_rate":      round(win_rate * 100, 1),
        "avg_win":       round(avg_win * 100, 2),
        "avg_loss":      round(avg_loss * 100, 2),
        "profit_factor": round(min(profit_factor, 99), 2),
        "expectancy":    round(expectancy * 100, 2),
        "total_ret":     round(total_ret * 100, 2),
        "cagr":          round(cagr * 100, 2),
        "annual_vol":    round(annual_vol * 100, 2),
        "sharpe":        round(sharpe, 3),
        "sortino":       round(sortino, 3),
        "max_drawdown":  round(max_dd * 100, 2),
        "calmar":        round(calmar, 3),
        "var_95":        round(var_95, 2),
        "benchmark_ret": round(bh_ret, 2),
    }


def _monte_carlo(trades: list, equity: list, n_sim: int = 1000) -> dict:
    if len(trades) < 5:
        return {}
    rets    = np.array([t["return_pct"] / 100 for t in trades])
    n       = len(rets)
    capital = equity[0]
    finals  = np.array([
        capital * np.prod(1 + np.random.choice(rets, size=n, replace=True))
        for _ in range(n_sim)
    ])
    p5, p25, p50, p75, p95 = np.percentile(finals, [5, 25, 50, 75, 95])
    return {
        "p5":  round(p5), "p25": round(p25), "p50": round(p50),
        "p75": round(p75), "p95": round(p95),
        "prob_profit": round(float((finals > capital).mean()) * 100, 1),
    }


def _walk_forward(df: pd.DataFrame, params: dict, n_splits: int = 5,
                  hold_days: int = 5, stop_pct: float = 0.05,
                  target_pct: float = 0.10, capital: float = 10_000_000) -> dict:
    """
    워크포워드 검증:
    전체 기간을 n_splits개 블록으로 분할 → 각 블록 OOS(Out-Of-Sample) 성과 측정
    과적합 방지를 위한 실전 성과 추정.
    """
    n          = len(df)
    block_size = n // n_splits
    periods    = []

    for i in range(n_splits):
        start = i * block_size
        end   = min(start + block_size, n)
        if end - start < 30:
            continue

        sub_df  = df.iloc[start:end]
        signal  = _build_entry_signal(sub_df, params)
        result  = _simulate(sub_df, signal, hold_days, stop_pct, target_pct, capital)
        trades  = result["trades"]
        equity  = result["equity"]

        bh   = (sub_df["close"].iloc[-1] - sub_df["close"].iloc[0]) / sub_df["close"].iloc[0] * 100
        mets = _compute_full_metrics(trades, equity, float(bh))

        periods.append({
            "period":    i + 1,
            "start":     sub_df.index[0].strftime("%Y-%m-%d"),
            "end":       sub_df.index[-1].strftime("%Y-%m-%d"),
            "n_trades":  len(trades),
            "total_ret": mets.get("total_ret", 0),
            "sharpe":    mets.get("sharpe", 0),
            "win_rate":  mets.get("win_rate", 0),
            "max_dd":    mets.get("max_drawdown", 0),
            "benchmark": round(float(bh), 2),
        })

    if not periods:
        return {"ok": False, "error": "기간 분할 실패"}

    avg_sharpe  = np.mean([p["sharpe"]    for p in periods])
    avg_ret     = np.mean([p["total_ret"] for p in periods])
    profitable  = sum(1 for p in periods if p["total_ret"] > 0)
    beat_bh     = sum(1 for p in periods if p["total_ret"] > p["benchmark"])

    return {
        "ok": True,
        "periods": periods,
        "summary": {
            "avg_sharpe":  round(avg_sharpe, 3),
            "avg_ret":     round(avg_ret, 2),
            "profitable":  profitable,
            "beat_bh":     beat_bh,
            "total":       len(periods),
            "consistency": round(profitable / len(periods) * 100, 1),
        },
    }


def _param_optimize(df: pd.DataFrame, hold_days: int = 5,
                    stop_pct: float = 0.05, target_pct: float = 0.10,
                    capital: float = 10_000_000) -> dict:
    """
    복합신호 임계값 그리드 서치 → Sharpe 최대 파라미터 탐색.
    threshold 0.0 ~ 1.2 (0.1 간격)
    """
    grid = np.arange(-0.5, 1.5, 0.2)
    best = {"sharpe": -99, "threshold": 0.5, "metrics": {}}
    rows = []

    for thr in grid:
        params  = {"mode": "composite", "composite_threshold": float(thr)}
        signal  = _build_entry_signal(df, params)
        result  = _simulate(df, signal, hold_days, stop_pct, target_pct, capital)
        trades  = result["trades"]
        equity  = result["equity"]
        bh      = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100
        mets    = _compute_full_metrics(trades, equity, float(bh))
        if not mets:
            continue

        row = {
            "threshold": round(float(thr), 2),
            "n_trades":  mets.get("n_trades", 0),
            "sharpe":    mets.get("sharpe", 0),
            "total_ret": mets.get("total_ret", 0),
            "win_rate":  mets.get("win_rate", 0),
            "max_dd":    mets.get("max_drawdown", 0),
        }
        rows.append(row)

        if row["sharpe"] > best["sharpe"] and row["n_trades"] >= 3:
            best = {"sharpe": row["sharpe"], "threshold": row["threshold"], "metrics": mets}

    return {"ok": True, "grid": rows, "best": best}


# ══════════════════════════════════════════════════════════════
# 3. 포트폴리오 최적화
# ══════════════════════════════════════════════════════════════

def _portfolio_stats(w, mu, cov):
    ret = float(w @ mu) * TRADING_DAYS
    vol = float(np.sqrt(w @ cov @ w)) * np.sqrt(TRADING_DAYS)
    sr  = (ret - RF_ANNUAL) / vol if vol > 1e-9 else 0.0
    return ret, vol, sr


def _max_sharpe(mu, cov, n, max_w=0.40):
    def neg_sr(w):
        r, v, _ = _portfolio_stats(w, mu, cov)
        return -(r - RF_ANNUAL) / (v + 1e-9)
    res = minimize(neg_sr, np.ones(n) / n, method="SLSQP",
                   bounds=[(0.0, max_w)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                   options={"maxiter": 1000, "ftol": 1e-12})
    w = np.clip(res.x, 0, None); return w / w.sum()


def _min_variance(mu, cov, n, max_w=0.40):
    res = minimize(lambda w: float(w @ cov @ w), np.ones(n) / n, method="SLSQP",
                   bounds=[(0.0, max_w)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                   options={"maxiter": 1000, "ftol": 1e-12})
    w = np.clip(res.x, 0, None); return w / w.sum()


def _risk_parity(cov, n):
    def _obj(w):
        pv = float(w @ cov @ w)
        rc = w * (cov @ w)
        return float(np.sum((rc - pv / n) ** 2))
    res = minimize(_obj, np.ones(n) / n, method="SLSQP",
                   bounds=[(1e-6, 1.0)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                   options={"maxiter": 2000, "ftol": 1e-14})
    w = np.clip(res.x, 0, None); return w / w.sum()


def _cvar_optimize(returns: pd.DataFrame, confidence: float = 0.95,
                   max_w: float = 0.40) -> np.ndarray:
    """
    CVaR(Expected Shortfall) 최소화 포트폴리오
    Rockafellar-Uryasev(2000) 선형화 공식:
      min  z + (1/((1-α)T)) Σ max(-r_t'w - z, 0)
    """
    n   = len(returns.columns)
    R   = returns.values   # T × n

    def cvar_obj(params):
        w = params[:n]
        z = params[n]
        port_rets  = R @ w
        shortfalls = np.maximum(-port_rets - z, 0)
        return z + shortfalls.mean() / (1 - confidence)

    w0     = np.ones(n) / n
    z0     = np.array([0.0])
    x0     = np.concatenate([w0, z0])
    bounds = [(0.0, max_w)] * n + [(-0.5, 0.5)]
    constr = [{"type": "eq", "fun": lambda x: x[:n].sum() - 1}]

    res = minimize(cvar_obj, x0, method="SLSQP", bounds=bounds,
                   constraints=constr, options={"maxiter": 2000, "ftol": 1e-12})
    w = np.clip(res.x[:n], 0, None); return w / w.sum()


def _efficient_frontier(mu, cov, n, n_points=30):
    mu_ann  = mu * TRADING_DAYS
    cov_ann = cov * TRADING_DAYS
    points  = []
    for tgt in np.linspace(float(mu_ann.min()), float(mu_ann.max()), n_points):
        res = minimize(lambda w: float(w @ cov_ann @ w), np.ones(n) / n,
                       method="SLSQP", bounds=[(0.0, 1.0)] * n,
                       constraints=[
                           {"type": "eq", "fun": lambda w: w.sum() - 1},
                           {"type": "eq", "fun": lambda w, t=tgt: float(w @ mu_ann) - t},
                       ],
                       options={"maxiter": 500, "ftol": 1e-10})
        if res.success:
            vol = float(np.sqrt(res.fun))
            points.append({"ret": round(tgt * 100, 2), "vol": round(vol * 100, 2),
                           "sharpe": round((tgt - RF_ANNUAL) / vol if vol > 0 else 0, 3)})
    return points


def _risk_contribution(w, cov):
    pv  = float(np.sqrt(w @ cov @ w))
    if pv < 1e-9: return np.ones(len(w)) / len(w)
    rc  = w * (cov @ w) / pv
    return rc / rc.sum()


# ══════════════════════════════════════════════════════════════
# 4. 리스크 관리
# ══════════════════════════════════════════════════════════════

def _var_historical(returns, confidence=0.95, capital=10_000_000):
    return float(-np.percentile(returns, (1 - confidence) * 100) * capital)

def _cvar_historical(returns, confidence=0.95, capital=10_000_000):
    cutoff = np.percentile(returns, (1 - confidence) * 100)
    tail   = returns[returns <= cutoff]
    return float(-tail.mean() * capital) if len(tail) > 0 else 0.0

def _var_parametric(mu, sigma, confidence=0.95, capital=10_000_000):
    z = stats.norm.ppf(1 - confidence)
    return float(-(mu + z * sigma) * capital)

def _kelly_criterion(returns):
    mu, sigma = float(returns.mean()), float(returns.std())
    kelly_cont = mu / (sigma ** 2) if sigma > 1e-9 else 0.0
    wins   = returns[returns > 0]
    losses = returns[returns < 0]
    p  = len(wins) / len(returns) if len(returns) > 0 else 0
    b  = (wins.mean() / (-losses.mean())) if len(losses) > 0 and losses.mean() != 0 else 1.0
    kelly_bin = (p * b - (1 - p)) / b if b > 0 else 0.0
    return round(max(0.0, min(float(min(kelly_cont, kelly_bin)), 0.5)), 4)

def _atr_position_size(price, atr, capital, risk_pct=0.01):
    max_loss = capital * risk_pct
    stop_dist = 2 * atr
    if stop_dist < 1e-9 or price < 1e-9:
        return {"shares": 0, "position_value": 0, "stop_price": 0,
                "risk_amount": 0, "position_pct": 0}
    shares = int(max_loss / stop_dist)
    return {
        "shares":         shares,
        "position_value": round(shares * price),
        "stop_price":     round(price - stop_dist),
        "risk_amount":    round(shares * stop_dist),
        "position_pct":   round(shares * price / capital * 100, 1),
    }

def _volatility_target(returns, target_vol=0.15):
    rv = float(returns.std()) * np.sqrt(TRADING_DAYS)
    return round(min(target_vol / rv, 2.0), 4) if rv > 1e-9 else 1.0

def _stress_test(returns: np.ndarray, capital: float) -> list:
    """과거 위기 시나리오 재현 (연율 수익률 → 1일 손실 환산)"""
    scenarios = [
        {"name": "코로나 폭락 (2020.03)",  "shock": -0.30},
        {"name": "금융위기 (2008.10)",     "shock": -0.25},
        {"name": "급락 -2σ (일별)",        "shock": float(-2 * returns.std())},
        {"name": "급락 -3σ (일별)",        "shock": float(-3 * returns.std())},
        {"name": "10% 급락",              "shock": -0.10},
        {"name": "20% 조정",              "shock": -0.20},
    ]
    return [{"name": s["name"],
             "shock_pct": round(s["shock"] * 100, 2),
             "loss_amt":  round(-s["shock"] * capital)} for s in scenarios]


# ══════════════════════════════════════════════════════════════
# 5. 전략 스캐너
# ══════════════════════════════════════════════════════════════

def _scan_one(code: str, meta: dict) -> dict | None:
    """단일 종목 신호 계산 (스캐너용)"""
    try:
        df = _load_ohlcv(code, 120)
        if df is None or len(df) < 60:
            return None
        sig = _compute_signals(df)
        if sig.empty or len(sig) < 2:
            return None

        lat  = sig.iloc[-1]
        prev = sig.iloc[-2]

        # 추가 패턴 감지
        macd_cross   = bool(lat["macd_hist"] > 0 and prev["macd_hist"] <= 0)
        stoch_cross  = bool(lat["stoch_k"] > lat["stoch_d"] and prev["stoch_k"] <= prev["stoch_d"])
        bb_squeeze   = bool(lat["bb_width"] < sig["bb_width"].quantile(0.2))
        vol_surge    = bool(lat["vol_ratio"] > 2.0)
        above_ma200  = bool(lat["close"] > lat["ma200"])

        # Hurst (마지막 60개 데이터)
        h = _hurst_exponent(df["close"].values[-60:])

        return {
            "code":        code,
            "name":        meta.get(code, {}).get("name", code),
            "close":       int(lat["close"]),
            "composite":   round(float(lat["composite"]), 3),
            "rsi":         round(float(lat["rsi"]), 1),
            "stoch_k":     round(float(lat["stoch_k"]), 1),
            "bb_pct":      round(float(lat["bb_pct"]), 1),
            "mom20":       round(float(lat["mom20"]), 2),
            "vol_ratio":   round(float(lat["vol_ratio"]), 2),
            "vwap_dev":    round(float(lat["vwap_dev"]), 2),
            "atr_pct":     round(float(lat["atr_pct"]), 2),
            "macd_cross":  macd_cross,
            "stoch_cross": stoch_cross,
            "bb_squeeze":  bb_squeeze,
            "vol_surge":   vol_surge,
            "above_ma200": above_ma200,
            "hurst":       h,
        }
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# 라우트
# ══════════════════════════════════════════════════════════════

@router.get("/quant")
def quant_page(request: Request):
    meta  = _load_meta()
    codes = sorted([p.stem for p in OHLCV_DIR.glob("*.parquet")]) if OHLCV_DIR.exists() else []
    names = {c: meta.get(c, {}).get("name", c) for c in codes}
    return render(request, "stock/quant.html", {"codes": codes, "names": names})


# ── 1. 신호 분석 ──────────────────────────────────────────────
@router.post("/api/quant/signals")
def api_signals(request: Request, body: dict = Body(default={})):
    code     = (body.get("code") or "").strip().lstrip("A")
    lookback = int(body.get("lookback", 252))

    if not code:
        return JSONResponse({"ok": False, "error": "종목 코드를 입력해주세요"}, status_code=400)

    df = _load_ohlcv(code, lookback)
    if df is None:
        return JSONResponse({"ok": False, "error": f"{code} 데이터 없음"}, status_code=404)

    sig    = _compute_signals(df)
    regime = _detect_regime(df["close"]).reindex(sig.index)
    tail   = sig.tail(120)
    rtail  = regime.reindex(tail.index)

    # Hurst 지수 (전체 기간)
    hurst = _hurst_exponent(df["close"].values)

    latest = {col: round(float(sig[col].iloc[-1]), 3) for col in sig.columns if col != "close"}
    latest["close"] = int(sig["close"].iloc[-1])

    return {
        "ok":     True,
        "code":   code,
        "name":   _load_meta().get(code, {}).get("name", code),
        "dates":  [d.strftime("%Y-%m-%d") for d in tail.index],
        "data":   {col: tail[col].tolist() for col in tail.columns},
        "regime": {
            "dates":      [d.strftime("%Y-%m-%d") for d in rtail.index],
            "regime":     rtail["regime"].tolist(),
            "trend_bull": rtail["trend_bull"].tolist(),
            "vol_low":    rtail["vol_low"].tolist(),
            "ma50":       rtail["ma50"].tolist(),
            "ma200":      rtail["ma200"].tolist(),
        },
        "hurst":   hurst,
        "latest":  latest,
    }


# ── 2. 백테스팅 ───────────────────────────────────────────────
@router.post("/api/quant/backtest")
def api_backtest(request: Request, body: dict = Body(default={})):
    code       = (body.get("code") or "").strip().lstrip("A")
    lookback   = int(body.get("lookback",   504))
    hold_days  = int(body.get("hold_days",    5))
    stop_pct   = float(body.get("stop_pct",  0.05))
    target_pct = float(body.get("target_pct", 0.10))
    capital    = float(body.get("capital", 10_000_000))
    params     = body.get("signal_params", {"mode": "composite", "composite_threshold": 0.5})
    n_sim      = int(body.get("n_sim", 500))

    if not code:
        return JSONResponse({"ok": False, "error": "종목 코드를 입력해주세요"}, status_code=400)

    df = _load_ohlcv(code, lookback)
    if df is None or len(df) < 60:
        return JSONResponse({"ok": False, "error": f"{code} 데이터 부족"}, status_code=404)

    signal  = _build_entry_signal(df, params)
    result  = _simulate(df, signal, hold_days, stop_pct, target_pct, capital)
    trades  = result["trades"]
    equity  = result["equity"]
    bh_ret  = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100
    metrics = _compute_full_metrics(trades, equity, float(bh_ret))
    mc      = _monte_carlo(trades, equity, n_sim)

    equity_norm = [round(e / equity[0] * 100, 2) for e in equity]
    eq_dates    = [df.index[0].strftime("%Y-%m-%d")] + [t["exit_date"] for t in trades]

    return {
        "ok":            True, "code": code,
        "trades":        trades[-100:],
        "equity":        equity_norm,
        "eq_dates":      eq_dates,
        "metrics":       metrics,
        "monte_carlo":   mc,
        "benchmark_ret": round(float(bh_ret), 2),
    }


@router.post("/api/quant/walkforward")
def api_walkforward(request: Request, body: dict = Body(default={})):
    code       = (body.get("code") or "").strip().lstrip("A")
    n_splits   = int(body.get("n_splits",   5))
    hold_days  = int(body.get("hold_days",  5))
    stop_pct   = float(body.get("stop_pct", 0.05))
    target_pct = float(body.get("target_pct", 0.10))
    capital    = float(body.get("capital", 10_000_000))
    params     = body.get("signal_params", {"mode": "composite", "composite_threshold": 0.5})

    if not code:
        return JSONResponse({"ok": False, "error": "종목 코드를 입력해주세요"}, status_code=400)

    df = _load_ohlcv(code, 756)
    if df is None or len(df) < 120:
        return JSONResponse({"ok": False, "error": "데이터 부족 (최소 3년 권장)"}, status_code=404)

    return _walk_forward(df, params, n_splits, hold_days, stop_pct, target_pct, capital)


@router.post("/api/quant/optimize")
def api_optimize(request: Request, body: dict = Body(default={})):
    code       = (body.get("code") or "").strip().lstrip("A")
    hold_days  = int(body.get("hold_days",  5))
    stop_pct   = float(body.get("stop_pct", 0.05))
    target_pct = float(body.get("target_pct", 0.10))
    capital    = float(body.get("capital", 10_000_000))

    if not code:
        return JSONResponse({"ok": False, "error": "종목 코드를 입력해주세요"}, status_code=400)

    df = _load_ohlcv(code, 504)
    if df is None or len(df) < 60:
        return JSONResponse({"ok": False, "error": "데이터 부족"}, status_code=404)

    return _param_optimize(df, hold_days, stop_pct, target_pct, capital)


# ── 3. 포트폴리오 최적화 ──────────────────────────────────────
@router.post("/api/quant/portfolio")
def api_portfolio(request: Request, body: dict = Body(default={})):
    codes    = body.get("codes", [])
    method   = body.get("method", "max_sharpe")
    max_w    = float(body.get("max_weight", 0.40))
    lookback = int(body.get("lookback", 504))

    if len(codes) < 2:
        return JSONResponse({"ok": False, "error": "종목 2개 이상 필요"}, status_code=400)

    returns = _load_returns(codes, lookback)
    if returns.empty or len(returns.columns) < 2:
        return JSONResponse({"ok": False, "error": "수익률 데이터 부족"}, status_code=400)

    valid = list(returns.columns)
    n     = len(valid)
    mu    = returns.mean().values
    cov   = returns.cov().values
    meta  = _load_meta()
    names = {c: meta.get(c, {}).get("name", c) for c in valid}

    if method == "max_sharpe":    w = _max_sharpe(mu, cov, n, max_w)
    elif method == "min_variance": w = _min_variance(mu, cov, n, max_w)
    elif method == "risk_parity":  w = _risk_parity(cov, n)
    elif method == "cvar":         w = _cvar_optimize(returns[valid], max_w=max_w)
    else:                          w = np.ones(n) / n

    ret, vol, sr = _portfolio_stats(w, mu, cov)
    rc           = _risk_contribution(w, cov)
    frontier     = _efficient_frontier(mu, cov, n) if n <= 10 else []

    w_eq              = np.ones(n) / n
    ret_eq, vol_eq, sr_eq = _portfolio_stats(w_eq, mu, cov)

    ind_stats = []
    for i, code in enumerate(valid):
        r_i = float(mu[i]) * TRADING_DAYS
        v_i = float(np.sqrt(cov[i, i])) * np.sqrt(TRADING_DAYS)
        ind_stats.append({
            "code": code, "name": names[code],
            "weight": round(float(w[i]), 4),
            "rc":     round(float(rc[i]), 4),
            "annual_ret": round(r_i * 100, 2),
            "annual_vol": round(v_i * 100, 2),
            "sharpe":     round((r_i - RF_ANNUAL) / v_i if v_i > 0 else 0, 3),
        })

    return {
        "ok": True, "method": method, "n_days": len(returns),
        "portfolio": {"annual_ret": round(ret * 100, 2),
                      "annual_vol": round(vol * 100, 2), "sharpe": round(sr, 3)},
        "baseline":  {"annual_ret": round(ret_eq * 100, 2),
                      "annual_vol": round(vol_eq * 100, 2), "sharpe": round(sr_eq, 3)},
        "stocks":    ind_stats,
        "frontier":  frontier,
        "missing":   [c for c in codes if c not in valid],
    }


# ── 4. 리스크 관리 ────────────────────────────────────────────
@router.post("/api/quant/risk")
def api_risk(request: Request, body: dict = Body(default={})):
    codes      = body.get("codes", [])
    capital    = float(body.get("capital", 10_000_000))
    risk_pct   = float(body.get("risk_per_trade", 0.01))
    target_vol = float(body.get("target_vol", 0.15))
    lookback   = int(body.get("lookback", 252))

    if not codes:
        return JSONResponse({"ok": False, "error": "종목 코드 필요"}, status_code=400)

    returns = _load_returns(codes, lookback)
    if returns.empty:
        return JSONResponse({"ok": False, "error": "데이터 부족"}, status_code=400)

    valid = list(returns.columns)
    meta  = _load_meta()
    names = {c: meta.get(c, {}).get("name", c) for c in valid}

    port_ret  = returns.mean(axis=1).values
    stock_risk = []

    for code in valid:
        r  = returns[code].values
        # _load_ohlcv는 최소 60행 필요 — 30이면 항상 None이라 사이징이 0주가 되던 버그
        df = _load_ohlcv(code, 90)
        last_close = float(df["close"].iloc[-1]) if df is not None else 0
        last_atr   = 0.0
        if df is not None:
            tr = pd.concat([df["high"] - df["low"],
                            (df["high"] - df["close"].shift(1)).abs(),
                            (df["low"]  - df["close"].shift(1)).abs()], axis=1).max(axis=1)
            last_atr = float(tr.ewm(span=14).mean().iloc[-1])

        mu_d, sig_d = float(r.mean()), float(r.std())
        ann_vol     = sig_d * np.sqrt(TRADING_DAYS)
        alloc       = capital / len(valid)

        stock_risk.append({
            "code":         code,
            "name":         names[code],
            "last_close":   int(last_close),
            "last_atr":     round(last_atr, 0),
            "annual_vol":   round(ann_vol * 100, 2),
            "var95_hist":   round(_var_historical(r, 0.95, alloc)),
            "var99_hist":   round(_var_historical(r, 0.99, alloc)),
            "cvar95":       round(_cvar_historical(r, 0.95, alloc)),
            "var95_param":  round(_var_parametric(mu_d, sig_d, 0.95, alloc)),
            "kelly":        round(_kelly_criterion(r) * 100, 1),
            "kelly_amount": round(_kelly_criterion(r) * capital),
            **_atr_position_size(last_close, last_atr, capital, risk_pct),
            "vol_leverage": _volatility_target(r, target_vol),
            "hurst":        _hurst_exponent(r[-60:] if len(r) >= 60 else r),
            "stress":       _stress_test(r, alloc),
        })

    port_ann_vol = float(port_ret.std()) * np.sqrt(TRADING_DAYS)
    corr = returns[valid].corr().round(3)

    return {
        "ok": True, "capital": capital,
        "stock_risk": stock_risk,
        "portfolio": {
            "annual_vol": round(port_ann_vol * 100, 2),
            "var95":      round(_var_historical(port_ret, 0.95, capital)),
            "var99":      round(_var_historical(port_ret, 0.99, capital)),
            "cvar95":     round(_cvar_historical(port_ret, 0.95, capital)),
        },
        "correlation": {
            "codes":  valid,
            "names":  [names[c] for c in valid],
            "matrix": corr.values.tolist(),
        },
    }


# ── 5. 전략 스캐너 ────────────────────────────────────────────
SCAN_CACHE = Path(__file__).parent.parent / "data" / "cache" / "quant_scan.json"


def run_market_scan(top_n: int = 50) -> dict:
    """전 종목 스캔 실행 + 결과를 캐시 파일에 저장.
    스케줄러(장 마감 후)와 수동 스캔 양쪽에서 사용."""
    meta  = _load_meta()
    codes = [p.stem for p in OHLCV_DIR.glob("*.parquet")] if OHLCV_DIR.exists() else []

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_scan_one, c, meta): c for c in codes}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: x["composite"], reverse=True)

    buy_signals  = results[:top_n]
    sell_signals = sorted(results, key=lambda x: x["composite"])[:top_n]

    n_macd_cross  = sum(1 for r in results if r["macd_cross"])
    n_stoch_cross = sum(1 for r in results if r["stoch_cross"])
    n_bb_squeeze  = sum(1 for r in results if r["bb_squeeze"])
    n_vol_surge   = sum(1 for r in results if r["vol_surge"])
    n_above_ma200 = sum(1 for r in results if r["above_ma200"])
    avg_composite = round(float(np.mean([r["composite"] for r in results])), 3) if results else 0

    payload = {
        "ok":           True,
        "total":        len(results),
        "scanned_at":   pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "market_stats": {
            "avg_composite":  avg_composite,
            "n_macd_cross":   n_macd_cross,
            "n_stoch_cross":  n_stoch_cross,
            "n_bb_squeeze":   n_bb_squeeze,
            "n_vol_surge":    n_vol_surge,
            "n_above_ma200":  n_above_ma200,
            "bull_ratio":     round(n_above_ma200 / len(results) * 100, 1) if results else 0,
        },
        "buy":  buy_signals,
        "sell": sell_signals,
    }
    try:
        SCAN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SCAN_CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload


def _trim_scan(payload: dict, top_n: int) -> dict:
    out = dict(payload)
    out["buy"]  = (payload.get("buy") or [])[:top_n]
    out["sell"] = (payload.get("sell") or [])[:top_n]
    return out


@router.get("/api/quant/scanner/cached")
def api_scanner_cached(request: Request):
    """마지막 스캔 결과 즉시 반환 (장 마감 후 자동 스캔 캐시)."""
    top_n = int(request.query_params.get("top_n", 20))
    if not SCAN_CACHE.exists():
        return {"ok": False, "cached": False}
    try:
        payload = json.loads(SCAN_CACHE.read_text(encoding="utf-8"))
        return {**_trim_scan(payload, top_n), "cached": True}
    except Exception:
        return {"ok": False, "cached": False}


@router.post("/api/quant/scanner")
def api_scanner(request: Request, body: dict = Body(default={})):
    top_n = int(body.get("top_n", 20))
    return _trim_scan(run_market_scan(top_n=max(top_n, 50)), top_n)
