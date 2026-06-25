"""
agent/event_calendar.py
========================
경제 이벤트 사전 알림 에이전트.
내일 예정된 주요 이벤트(FOMC, CPI, 금통위 등)를 LLM 브리핑과 함께 카카오 발송.

이벤트 등록:
  - 수동: from agent.event_calendar import add_event; add_event(...)
  - CLI: python -m agent.event_calendar --add "2026-07-01" "FOMC" "FOMC 금리 결정" "high" "US"

스케줄: 매일 18:00
수동:   python -m agent.event_calendar
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate
from agent.store import get_events_for_date, mark_event_notified, upsert_event

logger = logging.getLogger(__name__)

IMPORTANCE_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def add_event(
    event_date: str,
    event_type: str,
    title: str,
    importance: str = "medium",
    country: str = "US",
    description: str = "",
) -> int:
    """외부에서 이벤트를 직접 등록할 때 사용."""
    return upsert_event(event_date, event_type, title, description, importance, country)


def _build_briefing(events: list[dict], target_date: str) -> str:
    lines = []
    for e in events:
        emoji = IMPORTANCE_EMOJI.get(e.get("importance", "medium"), "🟡")
        line  = f"  {emoji} [{e.get('country','?')}] {e['title']}"
        if e.get("description"):
            line += f" — {e['description']}"
        lines.append(line)

    prompt = f"""내일({target_date}) 예정 경제 이벤트:

{"".join(l + chr(10) for l in lines)}
각 이벤트가 한국 주식시장에 미칠 수 있는 영향을 3-5문장으로 설명하세요:
- 예상 시나리오 (긍정/부정/중립)
- 주목할 지표나 수치
간결하게 작성하세요."""

    return generate(prompt, temperature=0.3, max_tokens=400)


def run(send_kakao: bool = True) -> dict:
    tomorrow     = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    events       = get_events_for_date(tomorrow)
    high_events  = [e for e in events if e.get("importance") == "high"]

    if not events:
        logger.info(f"[event_calendar] 내일({tomorrow}) 등록 이벤트 없음")
        return {"ok": True, "events": 0}

    # 중요도 낮은 이벤트 1건만 있으면 발송 생략
    if not high_events and len(events) < 2:
        logger.info("[event_calendar] 발송 기준 미달 — 스킵")
        return {"ok": True, "events": len(events), "skipped": True}

    briefing = _build_briefing(events, tomorrow)

    lines = ["📅 내일 경제 이벤트 알림", "─" * 20]
    for e in events:
        emoji = IMPORTANCE_EMOJI.get(e.get("importance", "medium"), "🟡")
        lines.append(f"{emoji} {e['title']}")
    if briefing:
        lines += ["", briefing[:400]]
    msg = "\n".join(lines)[:950]

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/market_reports", ai_generated=True)
            for e in events:
                mark_event_notified(e["id"])
            logger.info(f"[event_calendar] 발송 완료 ({len(events)}건)")
        except Exception as e:
            logger.warning(f"[event_calendar] 카카오톡 발송 실패: {e}")

    return {"ok": True, "events": len(events)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    args = sys.argv[1:]
    if args and args[0] == "--add":
        # python -m agent.event_calendar --add "날짜" "타입" "제목" "high" "US"
        if len(args) < 4:
            print("사용법: --add <날짜> <타입> <제목> [high|medium|low] [국가코드]")
            sys.exit(1)
        eid = add_event(
            event_date  = args[1],
            event_type  = args[2],
            title       = args[3],
            importance  = args[4] if len(args) > 4 else "medium",
            country     = args[5] if len(args) > 5 else "US",
        )
        print(f"이벤트 등록 완료: id={eid}")
    else:
        print(run())
