"""
agent/report_weekly.py
=======================
주간 시장 보고서 생성 및 저장/발송. 매주 금요일 18:00 실행.

  python -m agent.report_weekly
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from agent.data_collector import APP_BASE_URL, collect_weekly
from agent.llm_client import generate
from agent.store import get_report_by_date, save_report

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 한국 경제 및 금융 시장 전문 애널리스트입니다.
제공된 주간 데이터를 바탕으로 객관적이고 전문적인 주간 시장 보고서를 작성합니다.
매수/매도 의견은 절대 제시하지 않습니다.
이번 주 시장 흐름의 핵심 원인을 분석하고, 다음 주 주목할 변수를 식별합니다.
한국어로 작성하며, 구조적이고 분석적인 문체를 사용합니다."""


def _build_prompt(data: dict) -> str:
    macro   = data.get("macro", {})
    glb     = data.get("global", {})
    markets = data.get("markets", {})
    sectors = data.get("sectors", [])
    disc    = data.get("disclosures", [])
    news    = data.get("news", {})
    date    = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    week_start = data.get("week_start", "")

    # 국내 시장 주간 등락
    mkt_lines = []
    for name, info in markets.items():
        period_chg = info.get("period_change_pct")
        day_chg    = info.get("day_change_pct", 0)
        cur        = info.get("current")
        cur_str    = f"{cur:,.2f}" if isinstance(cur, (int, float)) else "-"
        if period_chg is not None:
            arrow = "▲" if period_chg >= 0 else "▼"
            mkt_lines.append(f"  - {name}: {cur_str} (주간 {arrow}{abs(period_chg):.2f}%, 전일 {day_chg:+.2f}%)")
    mkt_str = "\n".join(mkt_lines) if mkt_lines else "  - 데이터 없음"

    # 섹터 수익률
    if sectors:
        top3    = sectors[:3]
        bottom3 = sectors[-3:]
        sector_str = "  상위:\n" + "\n".join(
            f"    {i+1}. {s['sector']}: {s['return_pct']:+.2f}%" for i, s in enumerate(top3)
        )
        sector_str += "\n  하위:\n" + "\n".join(
            f"    {i+1}. {s['sector']}: {s['return_pct']:+.2f}%" for i, s in enumerate(bottom3)
        )
    else:
        sector_str = "  - 섹터 데이터 없음"

    # 글로벌
    sp500_ret  = glb.get("sp500_ret_5d", glb.get("sp500_ret_1d", 0)) * 100
    vix        = glb.get("vix_level", 0)
    oil_ret    = glb.get("oil_ret_20d", 0) * 100
    us_10y     = glb.get("us_10y", 0)

    # 거시
    usdkrw   = macro.get("usdkrw", "-")
    call_rate = macro.get("call_rate", "-")
    bond_3y  = macro.get("bond_3y", "-")

    # 주요 공시
    disc_lines = [f"  - {d.get('corp_name','?')}: {d.get('report_nm','?')}" for d in disc[:8]]
    disc_str = "\n".join(disc_lines) if disc_lines else "  - 주요 공시 없음"

    prompt = f"""아래는 {week_start} ~ {date} 주간 국내외 금융 시장 데이터입니다.

=== 국내 시장 주간 성과 ===
{mkt_str}

=== 섹터별 주간 수익률 ===
{sector_str}

=== 글로벌 시장 ===
  - S&P500 5일 수익률: {sp500_ret:+.2f}%
  - VIX (주 종가): {vix:.1f}
  - 유가 20일 추이: {oil_ret:+.2f}%
  - 미국 10년물 금리: {us_10y:.2f}%

=== 거시지표 (주 종가) ===
  - 원/달러: {usdkrw}
  - 콜금리: {call_rate}%
  - 국고채 3년: {bond_3y}%

=== 이번 주 주요 공시 ===
{disc_str}

---

위 데이터를 종합해 주간 시장 보고서를 아래 형식으로 작성해주세요:

## {week_start} ~ {date} 주간 시장 보고서

### 이번 주 시장 총평
(KOSPI/KOSDAQ 주간 흐름과 전반적인 시장 분위기 3-4문장)

### 섹터 동향 분석
(강세/약세 섹터의 원인과 배경 설명 3-4문장)

### 글로벌 변수 분석
(미국 시장, 금리, 달러 등 글로벌 변수가 국내 시장에 미친 영향 3-4문장)

### 이번 주 주요 공시 및 이벤트
(주목할 공시나 뉴스 이슈 요약)

### 다음 주 주목할 변수
(다음 주 시장에 영향을 줄 수 있는 주요 변수와 일정 3-5가지)

### 주간 시장 심리 평가
(VIX, 수급, 뉴스 감성을 종합한 시장 심리 상태 1-2문장)
"""
    return prompt


def _build_summary(content: str, week_start: str, date: str) -> str:
    header = f"📊 주간 시장 보고서 ({week_start} ~ {date})\n{'─'*20}\n"
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    return (header + "\n".join(lines[:40]))[:950]


def run(send_kakao: bool = True) -> dict:
    """주간 보고서 생성 → DB 저장 → 카카오톡 발송."""
    today = datetime.now()
    # 주간 보고서는 해당 주의 금요일 날짜로 키 설정
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    report_date = friday.strftime("%Y-%m-%d")
    week_start  = (friday - timedelta(days=4)).strftime("%Y-%m-%d")
    logger.info(f"[report_weekly] 시작: {week_start} ~ {report_date}")

    existing = get_report_by_date("weekly", report_date)
    if existing:
        logger.info("[report_weekly] 이번 주 보고서 이미 존재, 스킵")
        return {"ok": True, "skipped": True, "id": existing["id"]}

    data = collect_weekly()

    prompt = _build_prompt(data)
    logger.info("[report_weekly] LLM 보고서 생성 중...")
    content = generate(prompt, system=SYSTEM_PROMPT, temperature=0.3, max_tokens=3000)
    if not content:
        logger.error("[report_weekly] LLM 생성 실패")
        return {"ok": False, "error": "LLM 생성 실패"}

    title   = f"{week_start} ~ {report_date} 주간 시장 보고서"
    summary = _build_summary(content, week_start, report_date)

    report_id = save_report(
        report_type="weekly",
        report_date=report_date,
        title=title,
        content=content,
        summary=summary,
    )
    logger.info(f"[report_weekly] DB 저장 완료: id={report_id}")

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(
                summary,
                link_url=f"{APP_BASE_URL}/reports",
                ai_generated=True,
            )
            logger.info("[report_weekly] 카카오톡 발송 완료")
        except Exception as e:
            logger.warning(f"[report_weekly] 카카오톡 발송 실패: {e}")

    return {"ok": True, "id": report_id, "title": title}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    result = run()
    print(result)
