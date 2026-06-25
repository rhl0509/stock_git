"""
short_features.py — pykrx 공매도 피처.
SHORT_COLS = short_ratio_5d, short_ratio_20d, short_balance_pct
캐시: data/cache/short/{code}.json (6시간)
"""
import json, logging
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logger    = logging.getLogger(__name__)
ROOT      = Path(__file__).parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'short'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_HOURS = 6

SHORT_COLS = ["short_ratio_5d", "short_ratio_20d", "short_balance_pct"]
_ZERO = {c: 0.0 for c in SHORT_COLS}


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


def get_short_features(code: str) -> dict:
    """
    공매도 피처 3개.
      short_ratio_5d:    최근 5일 공매도 거래 비중 평균 (%)
      short_ratio_20d:   최근 20일 공매도 거래 비중 평균 (%)
      short_balance_pct: 공매도 잔고 비중 최신값 (%)
    """
    cached = _load_cache(code)
    if cached is not None:
        return cached

    try:
        from pykrx import stock as krx
        today = datetime.now()
        end   = today.strftime("%Y%m%d")
        start = (today - timedelta(days=60)).strftime("%Y%m%d")

        # ISIN 사전 확인 — None이면 pykrx 내부 에러 체인 방지
        try:
            if not krx.get_market_ticker_name(code):
                _save_cache(code, _ZERO)
                return _ZERO
        except Exception:
            pass

        vol_df = krx.get_shorting_volume_by_date(start, end, code)
        bal_df = krx.get_shorting_balance_by_date(start, end, code)

        result = _ZERO.copy()

        if vol_df is not None and not vol_df.empty and '비중' in vol_df.columns:
            pct = vol_df['비중'].dropna()
            if len(pct) >= 5:
                result['short_ratio_5d']  = float(pct.tail(5).mean())
            if len(pct) >= 10:
                result['short_ratio_20d'] = float(pct.tail(20).mean())

        if bal_df is not None and not bal_df.empty and len(bal_df.columns) >= 2:
            # 공매도잔고 / 상장주식수 직접 계산 (pykrx '비중' 컬럼은 정밀도 낮음)
            short_bal = bal_df.iloc[:, 0].dropna()
            listed    = bal_df.iloc[:, 1].dropna()
            if len(short_bal) > 0 and len(listed) > 0:
                ratio = float(short_bal.iloc[-1]) / (float(listed.iloc[-1]) + 1e-9) * 100
                result['short_balance_pct'] = round(ratio, 6)

        _save_cache(code, result)
        return result

    except Exception as e:
        logger.debug(f"[short] {code}: {e}")
        _save_cache(code, _ZERO)
        return _ZERO


if __name__ == '__main__':
    print(get_short_features("005930"))
