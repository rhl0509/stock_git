"""
sector_features.py — 유니버스 대비 상대강도 피처.
수집된 OHLCV 전체 평균 대비 개별 종목 상대 수익률 계산.
캐시: data/cache/sector/{code}.json (1시간)
"""
import json, logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger    = logging.getLogger(__name__)
ROOT      = Path(__file__).parent
OHLCV_DIR = ROOT / "data" / "ohlcv"
CACHE_DIR = ROOT / "data" / "cache" / "sector"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_HOURS = 1

SECTOR_COLS = ["ret_vs_univ_5d", "ret_vs_univ_20d", "rs_score_20d"]
_ZERO = {c: 0.0 for c in SECTOR_COLS}

_univ_cache: dict = {}   # {"built_at": datetime, "ret5": float, "ret20": float, "ranks": Series}


def _build_universe_stats() -> dict:
    """전체 수집 OHLCV에서 유니버스 평균 수익률 및 20일 수익률 분포 계산."""
    global _univ_cache
    now = datetime.now()
    if _univ_cache and (now - _univ_cache["built_at"]).total_seconds() < CACHE_HOURS * 3600:
        return _univ_cache

    files = list(OHLCV_DIR.glob("*.parquet"))
    if not files:
        return {}

    ret5_list, ret20_list, code_ret20 = [], [], {}

    for f in files:
        try:
            df = pd.read_parquet(f)
            c  = df["close"] if "close" in df.columns else df.iloc[:, 3]
            if len(c) < 25:
                continue
            r5  = float((c.iloc[-1] - c.iloc[-6])  / (c.iloc[-6]  + 1e-9))
            r20 = float((c.iloc[-1] - c.iloc[-21]) / (c.iloc[-21] + 1e-9))
            ret5_list.append(r5)
            ret20_list.append(r20)
            code_ret20[f.stem] = r20
        except Exception:
            continue

    if not ret5_list:
        return {}

    _univ_cache = {
        "built_at":   now,
        "avg_ret5":   float(np.mean(ret5_list)),
        "avg_ret20":  float(np.mean(ret20_list)),
        "code_ret20": code_ret20,
    }
    return _univ_cache


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def _load_cache(code: str):
    p = _cache_path(code)
    if not p.exists():
        return None
    if (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() > CACHE_HOURS * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(code: str, data: dict) -> None:
    try:
        _cache_path(code).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_sector_features(code: str) -> dict:
    """
    유니버스 상대강도 피처 3개.
      ret_vs_univ_5d:  개별 5일 수익률 - 유니버스 평균 5일 수익률
      ret_vs_univ_20d: 개별 20일 수익률 - 유니버스 평균 20일 수익률
      rs_score_20d:    유니버스 내 20일 수익률 백분위 순위 (0~1, 1=최상위)
    """
    cached = _load_cache(code)
    if cached is not None:
        return cached

    try:
        stats = _build_universe_stats()
        if not stats:
            return _ZERO

        parquet = OHLCV_DIR / f"{code}.parquet"
        if not parquet.exists():
            return _ZERO

        df = pd.read_parquet(parquet)
        c  = df["close"] if "close" in df.columns else df.iloc[:, 3]
        if len(c) < 25:
            return _ZERO

        r5  = float((c.iloc[-1] - c.iloc[-6])  / (c.iloc[-6]  + 1e-9))
        r20 = float((c.iloc[-1] - c.iloc[-21]) / (c.iloc[-21] + 1e-9))

        code_ret20 = stats.get("code_ret20", {})
        all_ret20  = list(code_ret20.values())

        rs_score = 0.5
        if all_ret20:
            below = sum(1 for v in all_ret20 if v <= r20)
            rs_score = round(below / len(all_ret20), 4)

        result = {
            "ret_vs_univ_5d":  round(r5  - stats["avg_ret5"],  6),
            "ret_vs_univ_20d": round(r20 - stats["avg_ret20"], 6),
            "rs_score_20d":    rs_score,
        }
        _save_cache(code, result)
        return result

    except Exception as e:
        logger.debug(f"[sector] {code}: {e}")
        _save_cache(code, _ZERO)
        return _ZERO


if __name__ == "__main__":
    print(get_sector_features("005930"))
