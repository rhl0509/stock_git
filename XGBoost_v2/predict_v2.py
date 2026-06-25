"""
XGBoost_v2/predict_v2.py
========================
개별 종목 단건 예측. routes/recommend.py 의 /recommend/stock/<code> 가 호출.

동작 방식:
  1. 최신 daily_recommend.json 에서 해당 종목 검색 → 있으면 그대로 반환
  2. 없으면 가격만 조회해서 기본 추천값 반환 (신뢰도 0.5)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / 'model'
OUTPUT_JSON = MODEL_DIR / 'daily_recommend.json'

_latest_cache: dict = {}
_latest_mtime: float = 0.0


def _load_latest() -> dict:
    """최신 추천 JSON 로드. 파일 없으면 빈 dict. mtime 불변 시 캐시 반환."""
    global _latest_cache, _latest_mtime
    if not OUTPUT_JSON.exists():
        return {}
    try:
        mtime = OUTPUT_JSON.stat().st_mtime
        if mtime == _latest_mtime:
            return _latest_cache
        with open(OUTPUT_JSON, 'r', encoding='utf-8') as f:
            _latest_cache = json.load(f)
        _latest_mtime = mtime
        return _latest_cache
    except Exception as e:
        logger.warning(f"[predict_v2] daily_recommend.json 로드 실패: {e}")
        return {}


def _find_in_recommendations(code: str, data: dict) -> dict | None:
    """추천 JSON 에서 해당 종목 찾기."""
    for category in ('daily', 'short', 'swing'):
        for item in data.get(category, []):
            if item.get('code') == code:
                return {**item, 'category': category, 'source': 'recommendation'}
    return None


def _quick_quote(code: str, name: str, market: str) -> dict:
    """추천에 없을 때 가격만 가져와서 기본 추천값 반환."""
    try:
        from korea_stock_data import KoreaStockData
        d = KoreaStockData()
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = d.krx.ohlcv(code, start, end)

        if df is None or df.empty:
            return {"error": f"{code} 가격 데이터 없음"}

        price = int(df['종가'].iloc[-1])
        return {
            'code': code,
            'name': name or code,
            'market': market or 'KOSPI',
            'price': price,
            'entry':  int(price * 0.997),
            'target': int(price * 1.05),
            'stop':   int(price * 0.97),
            'expected_return': 0.05,
            'confidence': 0.5,
            'category': 'unranked',
            'source': 'live_quote',
            'note': '추천 목록에 없음 - 기본값 반환',
        }
    except Exception as e:
        logger.error(f"[predict_v2] _quick_quote 실패: {e}")
        return {"error": str(e)}


def predict_ticker(code: str, name: str = '', market: str = '') -> dict:
    """
    개별 종목 예측.

    Args:
        code: 종목코드 (예: '005930')
        name: 종목명 (선택)
        market: 'KOSPI' 또는 'KOSDAQ' (선택)

    Returns:
        성공: {code, name, market, price, entry, target, stop,
               expected_return, confidence, category, source, ...}
        실패: {"error": "..."}
    """
    code = (code or '').strip()
    if not code:
        return {"error": "종목코드 필요"}

    # 1) 최신 추천에서 검색
    latest = _load_latest()
    found = _find_in_recommendations(code, latest)
    if found:
        return found

    # 2) 추천에 없으면 실시간 시세
    return _quick_quote(code, name, market)


# ─────────────────────────────────────────────────────────
# CLI 테스트
# ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '005930'
    print(json.dumps(predict_ticker(code), ensure_ascii=False, indent=2))