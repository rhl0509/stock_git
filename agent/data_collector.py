"""
agent/data_collector.py
========================
일간/주간/월간 보고서용 데이터 수집기.
기존 XGBoost_v2 모듈을 재사용하고 결과를 구조화된 dict로 반환.

  from agent.data_collector import collect_daily, collect_weekly, collect_monthly
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _close_series(df: "pd.DataFrame") -> "pd.Series | None":
    """yfinance 결과에서 'Close' 종가 Series를 안전하게 추출.

    yfinance>=0.2/1.x는 단일 종목도 MultiIndex 컬럼(('Close','^KS11'))으로 반환하므로
    df['Close']가 DataFrame이 되어 .tolist() 등에서 깨진다. 컬럼을 평탄화해 Series로 보장.
    """
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        # ('Close','^KS11') → 'Close' 레벨만 남김
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    close = df.get("Close")
    if close is None:
        return None
    if isinstance(close, pd.DataFrame):       # 같은 라벨이 여러 개면 첫 컬럼
        close = close.iloc[:, 0]
    return close.dropna()

ROOT = Path(__file__).parent.parent
RECOMMEND_JSON = ROOT / "XGBoost_v2" / "model" / "daily_recommend.json"
PAPER_TRADES_JSON = ROOT / "XGBoost_v2" / "model" / "paper_trades.json"

# 카카오 링크 등에 쓸 베이스 URL (localhost가 모바일에서 안 열리는 문제 방지)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5001")


# ─────────────────────────────────────────────────────────────────
# 개별 데이터 수집 함수
# ─────────────────────────────────────────────────────────────────

def _get_macro() -> dict:
    try:
        from XGBoost_v2.bok_client import get_macro_features
        return get_macro_features()
    except Exception as e:
        logger.warning(f"[data_collector] BOK 거시지표 수집 실패: {e}")
        return {}


def _get_global() -> dict:
    try:
        from XGBoost_v2.global_features import get_global_features
        return get_global_features()
    except Exception as e:
        logger.warning(f"[data_collector] 글로벌 지수 수집 실패: {e}")
        return {}


def _get_dart_disclosures(days: int = 1) -> list[dict]:
    """DART 전체 시장 최근 공시 목록."""
    try:
        from XGBoost_v2.dart_client import get_market_disclosures
        return get_market_disclosures(days=days) or []
    except Exception as e:
        logger.warning(f"[data_collector] DART 공시 수집 실패: {e}")
        return []


def _get_news_sentiment(keywords: list[str] | None = None) -> dict:
    try:
        from XGBoost_v2.naver_news import get_news_features
        kw = keywords or ["코스피", "코스닥", "주식시장"]
        results = {}
        for k in kw[:3]:
            feat = get_news_features(k)
            results[k] = {
                "sentiment":     feat.get("claude_sent", feat.get("rule_sent", 0.0)),
                "article_count": feat.get("article_count", 0),
                "top_titles":    feat.get("top_titles", [])[:3],
            }
        return results
    except Exception as e:
        logger.warning(f"[data_collector] 뉴스 감성 수집 실패: {e}")
        return {}


def _get_recommendations() -> dict:
    if not RECOMMEND_JSON.exists():
        return {}
    try:
        return json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_market_prices(n_trading_days: int) -> dict:
    """
    KOSPI/KOSDAQ 최근 N 거래일 가격.
    Fix: period는 달력일 기준이므로 거래일 × 1.5 + 10으로 충분히 여유 있게 요청.
    반환 필드: current, prev, day_change_pct, period_change_pct, prices
    """
    calendar_days = int(n_trading_days * 1.5) + 10
    tickers = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    result = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(
                ticker, period=f"{calendar_days}d",
                progress=False, auto_adjust=True,
            )
            closes = _close_series(df)
            if closes is None:
                continue
            closes = closes.tail(n_trading_days)
            if len(closes) < 2:
                continue
            first, last, prev = float(closes.iloc[0]), float(closes.iloc[-1]), float(closes.iloc[-2])
            result[name] = {
                "current":          round(last, 2),
                "prev":             round(prev, 2),
                "day_change_pct":   round((last / prev - 1) * 100, 2),
                "period_change_pct": round((last / first - 1) * 100, 2),
                "n_days":           len(closes),
                "prices":           [round(float(v), 2) for v in closes.tolist()],
            }
        except Exception as e:
            logger.warning(f"[data_collector] {name} 가격 수집 실패: {e}")
    return result


def _fetch_sector_etf(sector: str, ticker: str, n_trading_days: int) -> dict | None:
    """섹터 ETF 단일 종목 수익률 조회 (ThreadPoolExecutor 내부에서 호출)."""
    calendar_days = int(n_trading_days * 1.5) + 10
    try:
        df = yf.download(
            ticker, period=f"{calendar_days}d",
            progress=False, auto_adjust=True,
        )
        closes = _close_series(df)
        if closes is None or len(closes) < 2:
            logger.warning(f"[data_collector] 섹터 ETF 데이터 없음: {sector} ({ticker})")
            return None
        closes = closes.tail(n_trading_days)
        if len(closes) < 2:
            logger.warning(f"[data_collector] 섹터 ETF 데이터 부족: {sector} ({ticker}), {len(closes)}행")
            return None
        ret = (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100
        return {"sector": sector, "return_pct": round(ret, 2)}
    except Exception as e:
        logger.warning(f"[data_collector] 섹터 ETF 수집 실패: {sector} ({ticker}): {e}")
        return None


# 주의: 아래 ETF 코드는 KRX 상장 ETF 기준. 상장폐지/변경 시 수동 업데이트 필요.
# 코드가 맞는지 확인: https://finance.yahoo.com/quote/091160.KS
SECTOR_ETFS: dict[str, str] = {
    "반도체":    "091160.KS",  # KODEX 반도체
    "2차전지":   "305720.KS",  # TIGER 2차전지테마
    "바이오":    "227540.KS",  # KODEX 바이오
    "인터넷":    "139270.KS",  # TIGER 미디어컨텐츠
    "금융":      "091170.KS",  # KODEX 은행
    "자동차":    "091180.KS",  # KODEX 자동차
    "철강/소재": "102970.KS",  # TIGER 소재
    "에너지":    "143850.KS",  # TIGER 원유선물
}


def _get_sector_returns(n_trading_days: int = 5) -> list[dict]:
    """섹터 ETF 수익률 — yfinance 병렬 호출."""
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_fetch_sector_etf, sector, ticker, n_trading_days): sector
            for sector, ticker in SECTOR_ETFS.items()
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)
    results.sort(key=lambda x: x["return_pct"], reverse=True)
    return results


def _get_paper_trade_summary() -> dict:
    if not PAPER_TRADES_JSON.exists():
        return {}
    try:
        from bot.paper_trading import get_summary
        return get_summary()
    except Exception as e:
        logger.warning(f"[data_collector] 가상매매 성과 수집 실패: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────
# 보고서별 수집 함수
# ─────────────────────────────────────────────────────────────────

def collect_daily() -> dict:
    """일간 보고서 데이터 (전일 마감 기준)."""
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info("[collect_daily] 데이터 수집 시작")

    macro   = _get_macro()
    glb     = _get_global()
    markets = _get_market_prices(n_trading_days=2)
    disclosures = _get_dart_disclosures(days=1)
    news    = _get_news_sentiment(["코스피", "코스닥", "주식시장"])
    rec     = _get_recommendations()

    logger.info("[collect_daily] 완료")
    return {
        "report_type": "daily",
        "date":        today,
        "macro":       macro,
        "global":      glb,
        "markets":     markets,       # day_change_pct = 전일 대비
        "disclosures": disclosures[:10],
        "news":        news,
        "recommendations": {
            "base_date":  rec.get("base_date", today),
            "daily_top3": rec.get("daily", [])[:3],
            "short_top3": rec.get("short", [])[:3],
            "swing_top3": rec.get("swing", [])[:3],
        },
    }


def collect_weekly() -> dict:
    """주간 보고서 데이터 (최근 5 거래일)."""
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    logger.info("[collect_weekly] 데이터 수집 시작")

    macro   = _get_macro()
    glb     = _get_global()
    markets = _get_market_prices(n_trading_days=5)   # period_change_pct = 주간 수익률
    sectors = _get_sector_returns(n_trading_days=5)
    disclosures = _get_dart_disclosures(days=7)
    news    = _get_news_sentiment(["코스피 주간", "코스닥 주간", "경제"])

    logger.info("[collect_weekly] 완료")
    return {
        "report_type": "weekly",
        "date":        today.strftime("%Y-%m-%d"),
        "week_start":  week_start,
        "macro":       macro,
        "global":      glb,
        "markets":     markets,       # period_change_pct = 5거래일 수익률
        "sectors":     sectors,
        "disclosures": disclosures[:20],
        "news":        news,
    }


def collect_monthly() -> dict:
    """월간 보고서 데이터 (최근 22 거래일)."""
    today = datetime.now()
    month_str = today.strftime("%Y년 %m월")
    logger.info("[collect_monthly] 데이터 수집 시작")

    macro   = _get_macro()
    glb     = _get_global()
    markets = _get_market_prices(n_trading_days=22)  # period_change_pct = 월간 수익률
    sectors = _get_sector_returns(n_trading_days=22)
    disclosures = _get_dart_disclosures(days=30)
    paper   = _get_paper_trade_summary()
    news    = _get_news_sentiment(["경제 전망", "금리", "환율"])

    logger.info("[collect_monthly] 완료")
    return {
        "report_type":   "monthly",
        "date":          today.strftime("%Y-%m-%d"),
        "month":         month_str,
        "macro":         macro,
        "global":        glb,
        "markets":       markets,     # period_change_pct = 22거래일(월간) 수익률
        "sectors":       sectors,
        "disclosures":   disclosures[:30],
        "paper_trading": paper,
        "news":          news,
    }
