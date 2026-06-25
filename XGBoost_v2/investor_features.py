"""
investor_features.py — pykrx 수급 피처 (외인/기관 순매수 강도).
캐시: data/cache/investor/{code}.json (6시간)
단위: 십억 원 (1e9 KRW)
"""
import json, logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
load_dotenv()

logger    = logging.getLogger(__name__)
ROOT      = Path(__file__).parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'investor'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_HOURS = 6

INVESTOR_COLS = [
    "frgn_net_5d", "frgn_net_20d", "frgn_net_60d",
    "inst_net_5d", "inst_net_20d",
]
_ZERO = {c: 0.0 for c in INVESTOR_COLS}


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def _load_cache(code: str):
    p = _cache_path(code)
    if not p.exists():
        return None
    if (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() > CACHE_HOURS * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_cache(code: str, data: dict) -> None:
    try:
        _cache_path(code).write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _extract_net(df: pd.DataFrame, keyword: str) -> 'pd.Series | None':
    """외인/기관 순매수 컬럼 추출 (MultiIndex/일반 모두 지원)."""
    if isinstance(df.columns, pd.MultiIndex):
        for lv0 in df.columns.get_level_values(0).unique():
            if keyword in str(lv0):
                for lv1 in ['순매수', '순', 'Net']:
                    try:
                        return df[(lv0, lv1)]
                    except KeyError:
                        pass
    else:
        for col in df.columns:
            if keyword in str(col):
                return df[col]
    return None


def get_investor_features(code: str) -> dict:
    """
    외인/기관 순매수 피처 5개.
    pykrx get_market_trading_value_by_date 사용.
    """
    cached = _load_cache(code)
    if cached is not None:
        return cached

    try:
        from pykrx import stock as krx
        today = datetime.now()
        end   = today.strftime("%Y%m%d")
        start = (today - timedelta(days=90)).strftime("%Y%m%d")

        # ISIN 사전 확인 — None이면 pykrx 내부 에러 체인 방지
        try:
            if not krx.get_market_ticker_name(code):
                _save_cache(code, _ZERO)
                return _ZERO
        except Exception:
            pass

        df = krx.get_market_trading_value_by_date(start, end, code)
        if df is None or df.empty:
            _save_cache(code, _ZERO)
            return _ZERO

        frgn = _extract_net(df, '외국인')
        inst = _extract_net(df, '기관')
        if frgn is None or inst is None:
            _save_cache(code, _ZERO)
            return _ZERO

        scale = 1e9  # → 십억 원 단위

        def net_n(series: pd.Series, n: int) -> float:
            tail = series.tail(n)
            return float(tail.sum()) / scale if len(tail) > 0 else 0.0

        result = {
            "frgn_net_5d":  net_n(frgn, 5),
            "frgn_net_20d": net_n(frgn, 20),
            "frgn_net_60d": net_n(frgn, 60),
            "inst_net_5d":  net_n(inst,  5),
            "inst_net_20d": net_n(inst, 20),
        }
        _save_cache(code, result)
        return result

    except Exception as e:
        logger.debug(f"[investor] {code}: {e}")
        _save_cache(code, _ZERO)
        return _ZERO


if __name__ == '__main__':
    print(get_investor_features("005930"))
