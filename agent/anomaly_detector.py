"""
agent/anomaly_detector.py
==========================
이상 감지 에이전트.
비정상 거래량·급등락 종목을 감지하고 LLM이 관련 뉴스와 함께 원인 설명 후 카카오 발송.

감지 기준:
  - 거래량 급증: 당일 거래량 > 20일 평균 × VOLUME_SPIKE_RATIO
  - 가격 급변:  전일 대비 ±PRICE_SPIKE_PCT% 이상

감시 대상: DEFAULT_WATCHLIST + DB의 보유 종목 자동 포함

스케줄: 평일 10:00, 13:00, 15:00
수동: python -m agent.anomaly_detector
"""
from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate

logger = logging.getLogger(__name__)

VOLUME_SPIKE_RATIO = 3.0
PRICE_SPIKE_PCT    = 5.0

DEFAULT_WATCHLIST: list[tuple[str, str]] = [
    ("005930.KS", "삼성전자"),
    ("000660.KS", "SK하이닉스"),
    ("035420.KS", "NAVER"),
    ("051910.KS", "LG화학"),
    ("006400.KS", "삼성SDI"),
    ("207940.KS", "삼성바이오로직스"),
    ("068270.KS", "셀트리온"),
    ("005380.KS", "현대차"),
    ("000270.KS", "기아"),
    ("012330.KS", "현대모비스"),
]


def _build_watchlist() -> list[tuple[str, str]]:
    """보유 종목 DB + DEFAULT_WATCHLIST 합산."""
    tickers = list(DEFAULT_WATCHLIST)
    seen = {t for t, _ in tickers}
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT code, name FROM stock_holdings")
                for row in (cur.fetchall() or []):
                    ticker = row["code"] + ".KS"
                    if ticker not in seen:
                        tickers.append((ticker, row["name"]))
                        seen.add(ticker)
        finally:
            conn.close()
    except Exception:
        pass
    return tickers


def _scan() -> list[dict]:
    anomalies = []
    for ticker, name in _build_watchlist():
        try:
            df = yf.download(ticker, period="30d", progress=False, auto_adjust=True)
            if df.empty or len(df) < 5:
                continue
            close  = df["Close"].dropna()
            volume = df["Volume"].dropna()
            if len(close) < 2 or len(volume) < 2:
                continue

            today_close = float(close.iloc[-1])
            prev_close  = float(close.iloc[-2])
            today_vol   = float(volume.iloc[-1])
            avg_vol     = float(volume.iloc[:-1].tail(20).mean())

            price_chg = (today_close / prev_close - 1) * 100
            vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0

            signals = []
            if abs(price_chg) >= PRICE_SPIKE_PCT:
                signals.append(f"가격 {'급등' if price_chg > 0 else '급락'} {price_chg:+.1f}%")
            if vol_ratio >= VOLUME_SPIKE_RATIO:
                signals.append(f"거래량 {vol_ratio:.1f}배")

            if signals:
                anomalies.append({
                    "ticker":    ticker,
                    "name":      name,
                    "price":     today_close,
                    "price_chg": price_chg,
                    "vol_ratio": vol_ratio,
                    "signals":   signals,
                })
        except Exception as e:
            logger.debug(f"[anomaly] {ticker} 스캔 실패: {e}")

    return anomalies


def _explain(anomalies: list[dict]) -> str:
    lines = [f"  - {a['name']}: {', '.join(a['signals'])}" for a in anomalies]

    news_ctx: list[str] = []
    try:
        from XGBoost_v2.naver_news import get_news_features
        for a in anomalies[:3]:
            feat   = get_news_features(a["name"])
            titles = feat.get("top_titles", [])[:2]
            if titles:
                news_ctx.append(f"  [{a['name']}] " + " / ".join(titles))
    except Exception:
        pass

    news_str = "\n".join(news_ctx) if news_ctx else "  - 뉴스 없음"
    prompt = f"""이상 신호 감지 종목:
{"".join(l + chr(10) for l in lines)}
관련 뉴스:
{news_str}

각 종목의 이상 원인을 1-2줄로 분석하세요.
뉴스가 없으면 일반적 가능성을 언급하고 추측임을 명시하세요."""

    return generate(prompt, temperature=0.3, max_tokens=400)


def _save_results(anomalies: list[dict], explanation: str):
    """감지된 이상 종목을 agent_anomaly_results 테이블에 저장."""
    try:
        from database.db_connection import get_db_connection
        now  = datetime.now()
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                for a in anomalies:
                    cur.execute(
                        """INSERT INTO agent_anomaly_results
                           (detected_at, ticker, name, price, price_chg, vol_ratio, signals, explanation)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            now, a['ticker'], a['name'],
                            round(a['price'], 2),
                            round(a['price_chg'], 4),
                            round(a['vol_ratio'], 4),
                            ', '.join(a['signals']),
                            (explanation or '')[:2000],
                        ),
                    )
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[anomaly] DB 저장 실패: {e}")


def run(send_kakao: bool = True) -> dict:
    now = datetime.now()
    if now.weekday() >= 5 or not (9 <= now.hour < 16):
        logger.info("[anomaly] 장외/주말 — 스킵")
        return {"ok": True, "skipped": True}

    logger.info("[anomaly] 이상 감지 스캔 시작")
    anomalies = _scan()
    if not anomalies:
        logger.info("[anomaly] 이상 없음")
        return {"ok": True, "anomalies": 0}

    explanation = _explain(anomalies)
    _save_results(anomalies, explanation)

    lines = [f"🚨 이상 감지 ({now.strftime('%H:%M')})", "─" * 20]
    for a in anomalies:
        arrow = "▲" if a["price_chg"] >= 0 else "▼"
        lines.append(f"{a['name']}: {arrow}{abs(a['price_chg']):.1f}% | 거래량 {a['vol_ratio']:.1f}배")
    if explanation:
        lines += ["", explanation[:350]]
    msg = "\n".join(lines)[:950]

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/stock_live", ai_generated=True)
            logger.info(f"[anomaly] 카카오톡 발송 완료 ({len(anomalies)}건)")
        except Exception as e:
            logger.warning(f"[anomaly] 카카오톡 발송 실패: {e}")

    return {"ok": True, "anomalies": len(anomalies)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run())
