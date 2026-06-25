"""
routes/portfolio_opt.py — 포트폴리오 최적화 (scipy Sharpe 최대화).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Request, Depends, Body
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from scipy.optimize import minimize
from templates_config import render
from database.db_connection import get_db_connection

router = APIRouter(dependencies=[Depends(require_login_smart)])

OHLCV_DIR      = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ohlcv"
RECOMMEND_JSON = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "daily_recommend.json"
META_JSON      = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ticker_meta.json"
HISTORY_FILE   = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "portfolio_opt_history.json"

MAX_HISTORY = 20


def _load_history() -> list:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    except Exception:
        return []


def _save_history(records: list) -> None:
    HISTORY_FILE.write_text(json.dumps(records[-MAX_HISTORY:], ensure_ascii=False, indent=2), encoding="utf-8")

TRADING_DAYS = 252
RF_ANNUAL    = 0.035  # 무위험 수익률 (3.5%, 국고채 근사)


def _load_meta() -> dict:
    try:
        return json.loads(META_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _lookup_codes_by_name(names: list) -> dict:
    """종목명 → 코드 매핑. kr_stocks(권위 소스) 우선, 실패 시 ticker_meta 역인덱스 폴백."""
    if not names:
        return {}
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            ph = ",".join(["%s"] * len(names))
            cur.execute(f"SELECT code, name FROM kr_stocks WHERE name IN ({ph})", names)
            rows = cur.fetchall()
        conn.close()
        return {r["name"]: r["code"] for r in rows}
    except Exception:
        meta = _load_meta()
        rev = {}
        for code, info in meta.items():
            nm = info.get("name") if isinstance(info, dict) else None
            if nm and nm not in rev:
                rev[nm] = code
        return {n: rev[n] for n in names if n in rev}


def _lookup_names_by_code(codes: list) -> dict:
    """종목코드 → 종목명 매핑. kr_stocks(권위 소스) 조회, 실패 시 빈 dict."""
    if not codes:
        return {}
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            ph = ",".join(["%s"] * len(codes))
            cur.execute(f"SELECT code, name FROM kr_stocks WHERE code IN ({ph})", codes)
            rows = cur.fetchall()
        conn.close()
        return {r["code"]: r["name"] for r in rows}
    except Exception:
        return {}


def _lookup_market_by_code(codes: list) -> dict:
    """종목코드 → 시장(KOSPI/KOSDAQ) 매핑. yfinance 심볼 접미사 결정용."""
    if not codes:
        return {}
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            ph = ",".join(["%s"] * len(codes))
            cur.execute(f"SELECT code, market FROM kr_stocks WHERE code IN ({ph})", codes)
            rows = cur.fetchall()
        conn.close()
        return {r["code"]: r["market"] for r in rows}
    except Exception:
        return {}


def _ensure_ohlcv(codes: list) -> list:
    """parquet 없는 코드를 yfinance로 즉시 수집한다. 수집 후에도 데이터를 못 구한 코드 리스트 반환."""
    need = [c for c in codes if not (OHLCV_DIR / f"{c}.parquet").exists()]
    if not need:
        return []
    market_map = _lookup_market_by_code(need)
    try:
        from XGBoost_v2.collect_v2 import fetch_yfinance, save_ohlcv
    except Exception:
        return need

    still_missing = []
    for c in need:
        mk = market_map.get(c) or "KOSPI"
        try:
            df = fetch_yfinance(c, market=mk)
        except Exception:
            df = None
        if df is not None and len(df) >= 60:
            save_ohlcv(c, df)
        else:
            still_missing.append(c)
    return still_missing


def _resolve_codes(tokens: list) -> tuple:
    """입력 토큰(종목코드 또는 종목명)을 6자리 코드로 변환. (코드목록, 미해결명) 반환."""
    numeric, names = [], []
    for t in tokens:
        t = str(t).strip()
        if not t:
            continue
        if t.isdigit():
            numeric.append(t.zfill(6))
        else:
            names.append(t)

    name_map   = _lookup_codes_by_name(names)
    unresolved = [n for n in names if n not in name_map]

    resolved, seen = [], set()
    for c in numeric + [name_map[n] for n in names if n in name_map]:
        if c not in seen:
            seen.add(c)
            resolved.append(c)
    return resolved, unresolved


def _load_returns(codes: list, lookback_days: int = 252) -> pd.DataFrame:
    """코드 목록의 일별 로그수익률 DataFrame 반환."""
    frames = {}
    for code in codes:
        p = OHLCV_DIR / f"{code}.parquet"
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p, columns=["close"])
            df.index = pd.to_datetime(df.index)
            frames[code] = df["close"].sort_index()
        except Exception:
            pass

    if len(frames) < 2:
        return pd.DataFrame()

    # 가격 먼저 합친 뒤 ffill → 상장일 차이·공백 허용
    prices = pd.concat(frames, axis=1).sort_index()
    prices = prices.ffill().tail(lookback_days + 1)

    returns = np.log(prices / prices.shift(1)).iloc[1:]

    # 데이터가 충분한 컬럼만 유지 (80% 이상 존재)
    thresh = int(len(returns) * 0.8)
    returns = returns.dropna(thresh=thresh, axis=1)
    returns = returns.ffill().dropna()

    if len(returns.columns) < 2:
        return pd.DataFrame()

    return returns


def _neg_sharpe(weights: np.ndarray, mean_ret: np.ndarray, cov: np.ndarray) -> float:
    port_ret  = float(np.dot(weights, mean_ret)) * TRADING_DAYS
    port_vol  = float(np.sqrt(weights @ cov @ weights)) * np.sqrt(TRADING_DAYS)
    if port_vol < 1e-9:
        return 0.0
    return -(port_ret - RF_ANNUAL) / port_vol


def _optimize(returns: pd.DataFrame, max_weight: float = 0.40) -> dict:
    n      = len(returns.columns)
    mean_r = returns.mean().values
    cov    = returns.cov().values

    w0          = np.ones(n) / n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    bounds      = [(0.0, max_weight)] * n

    result = minimize(
        _neg_sharpe, w0,
        args=(mean_r, cov),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-9},
    )

    weights = result.x
    weights = np.clip(weights, 0, None)
    weights /= weights.sum()

    port_ret = float(np.dot(weights, mean_r)) * TRADING_DAYS
    port_vol = float(np.sqrt(weights @ cov @ weights)) * np.sqrt(TRADING_DAYS)
    sharpe   = (port_ret - RF_ANNUAL) / port_vol if port_vol > 1e-9 else 0.0

    return {
        "weights":    {c: round(float(w), 4) for c, w in zip(returns.columns, weights)},
        "annual_ret": round(port_ret * 100, 2),
        "annual_vol": round(port_vol * 100, 2),
        "sharpe":     round(sharpe, 3),
        "success":    bool(result.success),
    }


def _frontier_points(returns: pd.DataFrame, n_points: int = 30) -> list:
    """효율적 프론티어: 목표 수익률별 최소분산 포트폴리오."""
    n      = len(returns.columns)
    mean_r = returns.mean().values * TRADING_DAYS
    cov    = returns.cov().values * TRADING_DAYS

    r_min = float(mean_r.min())
    r_max = float(mean_r.max())
    targets = np.linspace(r_min, r_max, n_points)
    points  = []

    for tgt in targets:
        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1},
            {"type": "eq", "fun": lambda w, t=tgt: np.dot(w, mean_r) - t},
        ]
        bounds = [(0.0, 1.0)] * n
        res = minimize(
            lambda w: float(w @ cov @ w),
            np.ones(n) / n,
            method="SLSQP", bounds=bounds, constraints=constraints,
            options={"maxiter": 300, "ftol": 1e-9},
        )
        if res.success:
            vol = round(float(np.sqrt(res.fun)) * 100, 2)
            points.append({"ret": round(tgt * 100, 2), "vol": vol})

    return points


@router.get("/portfolio_opt")
def portfolio_opt_page(request: Request):
    return render(request, "stock/portfolio_opt.html")


@router.get("/api/portfolio_opt/candidates")
def api_candidates():
    meta = _load_meta()
    candidates = []

    # 오늘의 추천 종목 우선 (parquet 있는 것만)
    if RECOMMEND_JSON.exists():
        try:
            data  = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
            codes = set()
            for cat in ("triple", "daily", "short", "swing"):
                for p in data.get(cat, []):
                    codes.add(p["code"])
            for code in codes:
                if (OHLCV_DIR / f"{code}.parquet").exists():
                    name = meta.get(code, {}).get("name", code)
                    candidates.append({"code": code, "name": name, "source": "추천"})
        except Exception:
            pass

    # 나머지 OHLCV 종목 추가 (중복 제외)
    existing = {c["code"] for c in candidates}
    for p in sorted(OHLCV_DIR.glob("*.parquet")):
        code = p.stem
        if code not in existing:
            name = meta.get(code, {}).get("name", code)
            candidates.append({"code": code, "name": name, "source": "수집"})

    return candidates


@router.post("/api/portfolio_opt/optimize")
def api_optimize(request: Request, body: dict = Body(default={})):
    raw        = body.get("codes", [])
    max_weight = float(body.get("max_weight", 0.40))
    lookback   = int(body.get("lookback_days", 252))

    codes, unresolved = _resolve_codes(raw)
    if unresolved:
        return JSONResponse(
            {"ok": False, "error": f"찾을 수 없는 종목: {', '.join(unresolved)}"},
            status_code=400,
        )
    if len(codes) < 2:
        return JSONResponse({"ok": False, "error": "종목을 2개 이상 입력하세요"}, status_code=400)
    if not (0.05 <= max_weight <= 1.0):
        return JSONResponse({"ok": False, "error": "max_weight는 0.05~1.0 사이여야 합니다"}, status_code=400)

    _ensure_ohlcv(codes)  # parquet 없는 종목은 yfinance로 즉시 수집

    returns = _load_returns(codes, lookback)
    if returns.empty or len(returns.columns) < 2:
        no_data = [c for c in codes if not (OHLCV_DIR / f"{c}.parquet").exists()]
        detail  = f" (데이터 없는 종목: {', '.join(no_data)})" if no_data else " (parquet 파일 확인 필요)"
        return JSONResponse({"ok": False, "error": f"수익률 데이터 부족{detail}"}, status_code=400)

    missing  = [c for c in codes if c not in returns.columns]
    result   = _optimize(returns, max_weight)
    frontier = _frontier_points(returns) if len(returns.columns) <= 10 else []

    meta    = _load_meta()
    db_name = _lookup_names_by_code(codes)
    names   = {c: meta.get(c, {}).get("name") or db_name.get(c) or c for c in codes}

    # 이력 저장
    from datetime import datetime
    history = _load_history()
    history.append({
        "saved_at":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "codes":      list(returns.columns),
        "names":      names,
        "max_weight": max_weight,
        "lookback":   lookback,
        "n_days":     len(returns),
        "annual_ret": result["annual_ret"],
        "annual_vol": result["annual_vol"],
        "sharpe":     result["sharpe"],
        "weights":    result["weights"],
    })
    _save_history(history)

    return {
        "ok":       True,
        "result":   result,
        "frontier": frontier,
        "names":    names,
        "missing":  missing,
        "n_days":   len(returns),
    }


@router.get("/api/portfolio_opt/history")
def api_history():
    history = _load_history()
    return list(reversed(history))


@router.delete("/api/portfolio_opt/history")
def api_history_delete(index: int = -1, all: bool = False):
    if all:
        _save_history([])
        return {"ok": True}
    # index는 화면(최신순) 기준 위치. 저장은 과거순이라 뒤집어서 처리.
    history = _load_history()
    rev = list(reversed(history))
    if index < 0 or index >= len(rev):
        return JSONResponse({"error": "해당 이력을 찾을 수 없습니다."}, status_code=404)
    del rev[index]
    _save_history(list(reversed(rev)))
    return {"ok": True}
