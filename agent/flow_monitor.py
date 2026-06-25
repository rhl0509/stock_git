"""
agent/flow_monitor.py
======================
외국인·기관 수급 모니터링 에이전트.
pykrx로 당일 외국인+기관 순매수 상위 종목을 감지하고 LLM 분석 후 카카오 발송.

스케줄: 평일 15:40 (장 마감 직후)
수동:   python -m agent.flow_monitor
"""
from __future__ import annotations

import logging
from datetime import datetime

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate

logger = logging.getLogger(__name__)

TOP_N = 10


def _get_flow(date_str: str) -> list[dict]:
    """pykrx로 외국인+기관 순매수 상위 종목 반환."""
    try:
        from pykrx import stock as px
    except ImportError:
        logger.error("[flow_monitor] pykrx 패키지가 설치되지 않음")
        return []

    results = []
    try:
        df_foreign = px.get_market_net_purchases_of_equities_by_ticker(
            date_str, date_str, "KOSPI", "외국인"
        )
        df_inst = px.get_market_net_purchases_of_equities_by_ticker(
            date_str, date_str, "KOSPI", "기관합계"
        )
        if df_foreign is None or df_foreign.empty:
            return []

        # 순매수 컬럼 — pykrx 버전에 따라 '순매수' 또는 마지막 컬럼
        def _net(df, ticker):
            if df is None or ticker not in df.index:
                return 0
            row = df.loc[ticker]
            if "순매수" in row.index:
                return int(row["순매수"])
            return int(row.iloc[-1])

        tickers = set(df_foreign.index.tolist()) | set(
            df_inst.index.tolist() if df_inst is not None else []
        )
        for ticker in tickers:
            f_net = _net(df_foreign, ticker)
            i_net = _net(df_inst, ticker)
            combined = f_net + i_net
            if combined <= 0:
                continue
            try:
                name = px.get_market_ticker_name(ticker)
            except Exception:
                name = ticker
            results.append({
                "ticker":      ticker,
                "name":        name,
                "foreign_net": f_net,
                "inst_net":    i_net,
                "combined":    combined,
            })
    except Exception as e:
        logger.warning(f"[flow_monitor] 수급 데이터 수집 실패: {e}")
        return []

    results.sort(key=lambda x: x["combined"], reverse=True)
    return results[:TOP_N]


def _build_prompt(flows: list[dict], date_str: str) -> str:
    lines = [
        f"  {i+1}. {f['name']}({f['ticker']}) "
        f"외국인 {f['foreign_net']:+,} / 기관 {f['inst_net']:+,}"
        for i, f in enumerate(flows)
    ]
    return f"""{date_str} 외국인+기관 순매수 상위:

{"".join(l + chr(10) for l in lines)}
4문장 이내로:
1. 집중되는 섹터/테마
2. 이 수급 흐름의 의미"""


def run(send_kakao: bool = True) -> dict:
    now = datetime.now()
    if now.weekday() >= 5:
        logger.info("[flow_monitor] 주말 — 스킵")
        return {"ok": True, "skipped": True}

    date_str = now.strftime("%Y%m%d")
    logger.info(f"[flow_monitor] 수급 분석 시작: {date_str}")

    flows = _get_flow(date_str)
    if not flows:
        logger.info("[flow_monitor] 수급 데이터 없음")
        return {"ok": True, "stocks": 0}

    commentary = generate(_build_prompt(flows, now.strftime("%Y-%m-%d")), temperature=0.3, max_tokens=400)

    lines = ["💰 외국인·기관 수급 상위", "─" * 20]
    for f in flows[:5]:
        lines.append(f"{f['name']}: 외국인 {f['foreign_net']:+,} / 기관 {f['inst_net']:+,}")
    if commentary:
        lines += ["", commentary[:350]]
    msg = "\n".join(lines)[:950]

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/stock_live", ai_generated=True)
            logger.info(f"[flow_monitor] 카카오톡 발송 완료 ({len(flows)}건)")
        except Exception as e:
            logger.warning(f"[flow_monitor] 카카오톡 발송 실패: {e}")

    return {"ok": True, "stocks": len(flows)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run())
