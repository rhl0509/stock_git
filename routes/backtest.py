"""
routes/backtest.py — 백테스팅 시뮬레이터 API + 페이지.
"""
import json, pickle, re
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Request, Depends, Body
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from templates_config import render

router = APIRouter(dependencies=[Depends(require_login_smart)])

OHLCV_DIR = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ohlcv"
MODEL_DIR = Path(__file__).parent.parent / "XGBoost_v2" / "model"


def _load_ohlcv(code: str, start: str, end: str) -> pd.DataFrame | None:
    # 6자리 종목코드만 허용 — 경로 탈출(../) 차단
    if not re.fullmatch(r"\d{6}", code):
        return None
    path = OHLCV_DIR / f"{code}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df[(df.index >= start) & (df.index <= end)]


def _compute_metrics(trades: list, equity: list) -> dict:
    if not trades:
        return {"win_rate": 0, "avg_return": 0, "total_return": 0,
                "max_drawdown": 0, "n_trades": 0}

    rets     = [t["return_pct"] for t in trades]
    wins     = [r for r in rets if r > 0]
    eq       = np.array(equity)
    peak     = np.maximum.accumulate(eq)
    drawdown = ((eq - peak) / peak * 100)
    max_dd   = float(drawdown.min()) if len(drawdown) else 0.0

    return {
        "n_trades":     len(trades),
        "win_rate":     round(len(wins) / len(rets) * 100, 1),
        "avg_return":   round(float(np.mean(rets)), 2),
        "total_return": round(float(eq[-1] - eq[0]) / eq[0] * 100, 2) if len(eq) > 1 else 0,
        "max_drawdown": round(max_dd, 2),
    }


def _run_ml_backtest(code: str, df: pd.DataFrame,
                     label: str = "daily", threshold: float = 0.55,
                     hold_days: int = 3) -> dict:
    try:
        import xgboost as xgb
        from XGBoost_v2.feature_v2 import build_technical, get_macro, FULL_COLS

        scaler_path = MODEL_DIR / "scaler_v2.pkl"
        xgb_path    = MODEL_DIR / f"xgb_v2_{label}.json"
        feat_path   = MODEL_DIR / "feature_list_v2.json"
        if not scaler_path.exists() or not xgb_path.exists():
            return {"error": "모델 파일 없음 — 먼저 학습 필요"}

        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        with open(feat_path, "r", encoding="utf-8") as f:
            features = json.load(f)

        booster = xgb.Booster()
        booster.load_model(str(xgb_path))

        macro  = get_macro()
        tech   = build_technical(df)

        X_df = tech.copy()
        for col in features:
            if col not in X_df.columns:
                X_df[col] = 0.0
        X_df = X_df[features].replace([np.inf, -np.inf], 0).fillna(0)

        X_scaled = scaler.transform(X_df.values.astype(np.float32))
        proba    = booster.predict(xgb.DMatrix(X_scaled))

    except Exception as e:
        return {"error": f"ML 예측 실패: {e}"}

    return _simulate(df, pd.Series(proba, index=X_df.index),
                     threshold=threshold, hold_days=hold_days, strategy="ml")


def _compute_rsi(c: pd.Series, p: int = 14) -> pd.Series:
    d = c.diff()
    g = d.clip(lower=0).ewm(com=p - 1, min_periods=p).mean()
    l = (-d).clip(lower=0).ewm(com=p - 1, min_periods=p).mean()
    return 100 - 100 / (1 + g / (l + 1e-9))


def _build_signal(df: pd.DataFrame, conditions: dict) -> pd.Series:
    c, v = df["close"], df["volume"]
    signal = pd.Series(True, index=df.index)

    if conditions.get("rsi_buy"):
        rsi = _compute_rsi(c)
        signal &= rsi < float(conditions.get("rsi_threshold", 30))

    if conditions.get("macd_cross"):
        ema12 = c.ewm(span=12).mean()
        ema26 = c.ewm(span=26).mean()
        macd  = ema12 - ema26
        sig   = macd.ewm(span=9).mean()
        signal &= (macd > sig) & (macd.shift(1) <= sig.shift(1))

    if conditions.get("ma_cross"):
        ma5  = c.rolling(5).mean()
        ma20 = c.rolling(20).mean()
        signal &= (ma5 > ma20) & (ma5.shift(1) <= ma20.shift(1))

    if conditions.get("volume_surge"):
        avg_vol = v.rolling(20).mean()
        signal &= v > avg_vol * float(conditions.get("volume_mult", 2.0))

    if conditions.get("bb_bounce"):
        ma20  = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        lower = ma20 - 2 * std20
        signal &= c < lower

    return signal.fillna(False)


def _run_custom_backtest(code: str, df: pd.DataFrame,
                         conditions: dict, hold_days: int = 5,
                         stop_pct: float = 3.0, target_pct: float = 5.0) -> dict:
    signal = _build_signal(df, conditions)
    proba  = signal.astype(float)
    return _simulate(df, proba, threshold=0.5, hold_days=hold_days,
                     stop_pct=stop_pct / 100, target_pct=target_pct / 100,
                     strategy="custom")


def _simulate(df: pd.DataFrame, signal: pd.Series,
              threshold: float = 0.5, hold_days: int = 5,
              stop_pct: float = 0.03, target_pct: float = 0.05,
              strategy: str = "ml") -> dict:
    closes = df["close"].values
    dates  = df.index
    n      = len(closes)

    trades    = []
    equity    = [10_000_000]
    cash      = equity[0]
    position  = None

    for i, (dt, sig) in enumerate(zip(dates, signal)):
        price = closes[i]

        if position:
            entry_p = position["entry"]
            ret     = (price - entry_p) / entry_p

            exit_reason = None
            if ret >= target_pct:
                exit_reason = "target"
            elif ret <= -stop_pct:
                exit_reason = "stop"
            elif (i - position["idx"]) >= hold_days:
                exit_reason = "timeout"

            if exit_reason:
                pnl     = (price - entry_p) * position["shares"]
                cash   += price * position["shares"]
                ret_pct = ret * 100
                trades.append({
                    "entry_date":  position["date"].strftime("%Y-%m-%d"),
                    "exit_date":   dt.strftime("%Y-%m-%d"),
                    "entry_price": int(entry_p),
                    "exit_price":  int(price),
                    "return_pct":  round(ret_pct, 2),
                    "exit_reason": exit_reason,
                })
                equity.append(cash)
                position = None

        if position is None and float(sig) >= threshold and i + hold_days < n:
            shares   = int(cash * 0.95 / price)
            if shares > 0:
                cash    -= price * shares
                position = {"entry": price, "date": dt, "idx": i, "shares": shares}

    if position:
        price = closes[-1]
        pnl   = (price - position["entry"]) * position["shares"]
        cash += price * position["shares"]
        ret_pct = (price - position["entry"]) / position["entry"] * 100
        trades.append({
            "entry_date":  position["date"].strftime("%Y-%m-%d"),
            "exit_date":   dates[-1].strftime("%Y-%m-%d"),
            "entry_price": int(position["entry"]),
            "exit_price":  int(price),
            "return_pct":  round(ret_pct, 2),
            "exit_reason": "force",
        })
        equity.append(cash)

    metrics = _compute_metrics(trades, equity)
    bh_ret = round((closes[-1] - closes[0]) / closes[0] * 100, 2) if len(closes) > 1 else 0

    return {
        "strategy":   strategy,
        "trades":     trades[-50:],
        "equity":     [round(e / equity[0] * 100, 2) for e in equity],
        "dates":      [dates[0].strftime("%Y-%m-%d")] + [t["exit_date"] for t in trades],
        "metrics":    metrics,
        "benchmark":  bh_ret,
    }


@router.get("/backtest")
def backtest_page(request: Request):
    codes = sorted([p.stem for p in OHLCV_DIR.glob("*.parquet")]) if OHLCV_DIR.exists() else []
    return render(request, "stock/backtest.html", {"codes": codes})


_STRATEGY_CONDITIONS = {
    "rsi":      {"rsi_buy": True,      "rsi_threshold": 30},
    "macd":     {"macd_cross": True},
    "ma":       {"ma_cross": True},
    "volume":   {"volume_surge": True, "volume_mult": 2.0},
    "bollinger":{"bb_bounce": True},
}


@router.post("/backtest/run")
@router.post("/api/backtest/run")  # SPA 프론트엔드 /api/ 경로 호환
def run_backtest(request: Request, body: dict = Body(default={})):
    code       = body.get("code", "005930").strip().lstrip("A")
    strategy   = body.get("strategy", "ml")
    start      = body.get("start", "2023-01-01")
    end        = body.get("end",   datetime.now().strftime("%Y-%m-%d"))
    label      = body.get("label",      "daily")
    threshold  = float(body.get("threshold",  0.55))
    hold_days  = int(body.get("hold_days",    3))
    stop_pct   = float(body.get("stop_pct",  3.0))
    target_pct = float(body.get("target_pct", 5.0))
    conditions = body.get("conditions") or _STRATEGY_CONDITIONS.get(strategy, {})

    df = _load_ohlcv(code, start, end)
    if df is None:
        return JSONResponse({"error": f"{code} 데이터 없음 (수집 필요)"}, status_code=404)
    if len(df) < 60:
        return JSONResponse({"error": "데이터 부족 (최소 60일 필요)"}, status_code=400)

    if strategy == "ml":
        result = _run_ml_backtest(code, df, label=label,
                                  threshold=threshold, hold_days=hold_days)
    else:
        result = _run_custom_backtest(code, df, conditions=conditions,
                                      hold_days=hold_days,
                                      stop_pct=stop_pct, target_pct=target_pct)

    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


@router.get("/backtest/codes")
def available_codes():
    codes = sorted([p.stem for p in OHLCV_DIR.glob("*.parquet")]) if OHLCV_DIR.exists() else []
    return codes
