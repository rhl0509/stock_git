"""
agent/report_daily.py
======================
일간 시장 보고서 생성 및 저장/발송.

  python -m agent.report_daily
"""
from __future__ import annotations

import logging
from datetime import datetime

from agent.data_collector import APP_BASE_URL, collect_daily
from agent.llm_client import generate
from agent.store import get_report_by_date, save_report

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 한국 경제 및 금융 시장 전문 애널리스트입니다.
제공된 데이터를 바탕으로 객관적이고 전문적인 일간 시장 브리핑을 작성합니다.
매수/매도 의견은 절대 제시하지 않습니다.
데이터에 근거한 사실 중심의 해석과 시장 흐름 설명에 집중합니다.
한국어로 작성하며, 간결하고 명확한 문체를 사용합니다."""


def _build_prompt(data: dict) -> str:
    macro   = data.get("macro", {})
    glb     = data.get("global", {})
    markets = data.get("markets", {})
    disc    = data.get("disclosures", [])
    news    = data.get("news", {})
    rec     = data.get("recommendations", {})
    date    = data.get("date", datetime.now().strftime("%Y-%m-%d"))

    # 국내 시장
    mkt_lines = []
    for name, info in markets.items():
        cur = info.get("current")
        chg = info.get("day_change_pct", 0)
        arrow = "▲" if chg >= 0 else "▼"
        cur_str = f"{cur:,.2f}" if isinstance(cur, (int, float)) else "-"
        mkt_lines.append(f"  - {name}: {cur_str} ({arrow}{abs(chg):.2f}%)")
    mkt_str = "\n".join(mkt_lines) if mkt_lines else "  - 데이터 없음"

    # 글로벌
    sp500_ret  = glb.get("sp500_ret_1d", 0) * 100
    nasdaq_ret = glb.get("nasdaq_ret_1d", 0) * 100
    vix        = glb.get("vix_level", 0)
    oil_ret    = glb.get("oil_ret_20d", 0) * 100
    us_10y     = glb.get("us_10y", 0)

    # 거시
    usdkrw   = macro.get("usdkrw", "-")
    call_rate = macro.get("call_rate", "-")
    bond_3y  = macro.get("bond_3y", "-")
    cpi      = macro.get("cpi", "-")

    # 공시
    disc_lines = [f"  - {d.get('corp_name','?')}: {d.get('report_nm','?')}" for d in disc[:5]]
    disc_str = "\n".join(disc_lines) if disc_lines else "  - 주요 공시 없음"

    # 뉴스 감성
    news_lines = []
    for kw, info in news.items():
        sent = info.get("sentiment", 0)
        mood = "긍정적" if sent > 0.1 else "부정적" if sent < -0.1 else "중립"
        news_lines.append(f"  - '{kw}' 관련 뉴스 감성: {mood} ({sent:+.2f})")
    news_str = "\n".join(news_lines) if news_lines else "  - 뉴스 데이터 없음"

    # 추천 요약 (참고용, 매수/매도 의견 아님)
    def _fmt_picks(picks):
        if not picks:
            return "  - 없음"
        return "\n".join(f"  - {p.get('name','?')} ({p.get('code','?')}), 신뢰도 {p.get('confidence',0)*100:.0f}%" for p in picks)

    prompt = f"""아래는 {date} 기준 국내외 금융 시장 데이터입니다.

=== 국내 시장 ===
{mkt_str}

=== 글로벌 시장 (전일 기준) ===
  - S&P500 일간: {sp500_ret:+.2f}%
  - NASDAQ 일간: {nasdaq_ret:+.2f}%
  - VIX (공포지수): {vix:.1f}
  - 유가 20일 등락: {oil_ret:+.2f}%
  - 미국 10년물 금리: {us_10y:.2f}%

=== 거시지표 ===
  - 원/달러 환율: {usdkrw}
  - 콜금리: {call_rate}%
  - 국고채 3년: {bond_3y}%
  - CPI(전월): {cpi}

=== 오늘 주요 공시 ===
{disc_str}

=== 뉴스 감성 분석 ===
{news_str}

=== ML 모델 관심 종목 (참고용) ===
단기(3일):
{_fmt_picks(rec.get('daily_top3', []))}
스윙(14일):
{_fmt_picks(rec.get('swing_top3', []))}

---

위 데이터를 종합해 {date} 일간 시장 브리핑을 아래 형식으로 작성해주세요:

## {date} 일간 시장 브리핑

### 오늘의 시장 요약
(국내 주요 지수 동향과 특징 2-3문장)

### 글로벌 시장 동향
(미국 시장, VIX, 금리 등 글로벌 변수 해석 2-3문장)

### 거시경제 환경
(환율, 금리 등 거시지표가 시장에 미치는 영향 2문장)

### 주목할 공시 및 이슈
(오늘 공시 중 주목할 내용 또는 "특이 공시 없음")

### 시장 심리
(뉴스 감성과 VIX를 종합한 현재 시장 심리 1-2문장)

### 내일 주목할 포인트
(다음 거래일에 주시해야 할 변수 2-3가지)
"""
    return prompt


def _build_summary(content: str, date: str) -> str:
    """카카오톡 발송용 요약 (950자 이내). LLM 응답 구조에 무관하게 앞부분을 추출."""
    header = f"📰 {date} 일간 시장 브리핑\n{'─'*20}\n"
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    body = "\n".join(lines[:40])
    combined = header + body
    return combined[:950]


def run(send_kakao: bool = True) -> dict:
    """일간 보고서 생성 → DB 저장 → 카카오톡 발송."""
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"[report_daily] 시작: {today}")

    # 이미 오늘 보고서가 있으면 스킵
    existing = get_report_by_date("daily", today)
    if existing:
        logger.info("[report_daily] 오늘 보고서 이미 존재, 스킵")
        return {"ok": True, "skipped": True, "id": existing["id"]}

    # 1) 데이터 수집
    data = collect_daily()

    # 2) LLM 보고서 생성
    prompt = _build_prompt(data)
    logger.info("[report_daily] LLM 보고서 생성 중...")
    content = generate(prompt, system=SYSTEM_PROMPT, temperature=0.3, max_tokens=2048)
    if not content:
        logger.error("[report_daily] LLM 생성 실패")
        return {"ok": False, "error": "LLM 생성 실패"}

    title = f"{today} 일간 시장 브리핑"
    summary = _build_summary(content, today)

    # 3) DB 저장
    report_id = save_report(
        report_type="daily",
        report_date=today,
        title=title,
        content=content,
        summary=summary,
    )
    logger.info(f"[report_daily] DB 저장 완료: id={report_id}")

    # 4) 카카오톡 발송
    if send_kakao:
        try:
            from notify.send import send_message_to_self
            kakao_text = summary
            send_message_to_self(kakao_text, link_url=f"{APP_BASE_URL}/reports", ai_generated=True)
            logger.info("[report_daily] 카카오톡 발송 완료")
        except Exception as e:
            logger.warning(f"[report_daily] 카카오톡 발송 실패 (보고서는 저장됨): {e}")

    return {"ok": True, "id": report_id, "title": title}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    result = run()
    print(result)
