"""
agent/dart_summarizer.py
=========================
DART 공시 LLM 요약 에이전트.
중요 공시를 감지해 LLM이 호재/악재/중립 + 한 줄 요약으로 변환 후 카카오 발송.

스케줄: 평일 장중 매 60분 (10:00, 11:00, ..., 15:00)
수동:   python -m agent.dart_summarizer
"""
from __future__ import annotations

import logging
from datetime import datetime

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate
from agent.store import is_dart_summarized, save_dart_summary

logger = logging.getLogger(__name__)

SIGNAL_EMOJI = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}

IMPORTANT_KEYWORDS = [
    "주요사항보고", "유상증자", "무상증자", "전환사채", "신주인수권",
    "자기주식", "합병", "분할", "최대주주변경", "대표이사변경",
    "영업정지", "상장폐지", "단일판매공급계약", "분기보고서", "반기보고서",
]


def _is_important(report_nm: str) -> bool:
    return any(kw in report_nm for kw in IMPORTANT_KEYWORDS)


def _summarize(corp_name: str, report_nm: str) -> tuple[str, str]:
    """(signal, summary) 반환."""
    prompt = f"""DART 공시 분석:
회사: {corp_name}
제목: {report_nm}

형식:
신호: [호재/악재/중립]
요약: [30자 이내 핵심]"""

    result  = generate(prompt, temperature=0.2, max_tokens=100)
    signal  = "중립"
    summary = report_nm[:60]

    if result:
        for line in result.strip().split("\n"):
            line = line.strip()
            if line.startswith("신호:"):
                val = line[3:].strip()
                for s in ("호재", "악재", "중립"):
                    if s in val:
                        signal = s
                        break
            elif line.startswith("요약:"):
                summary = line[3:].strip()[:60]

    return signal, summary


def run(send_kakao: bool = True) -> dict:
    now = datetime.now()
    if now.weekday() >= 5 or not (9 <= now.hour < 16):
        logger.info("[dart_summarizer] 장외/주말 — 스킵")
        return {"ok": True, "skipped": True}

    logger.info("[dart_summarizer] 공시 요약 시작")
    try:
        from XGBoost_v2.dart_client import get_market_disclosures
        disclosures = get_market_disclosures(days=1) or []
    except Exception as e:
        logger.error(f"[dart_summarizer] 공시 수집 실패: {e}")
        return {"ok": False, "error": str(e)}

    targets = [
        d for d in disclosures
        if _is_important(d.get("report_nm", ""))
        and not is_dart_summarized(d.get("rcept_no", ""))
    ]

    if not targets:
        logger.info("[dart_summarizer] 새로운 중요 공시 없음")
        return {"ok": True, "summarized": 0}

    results = []
    for d in targets[:5]:
        rcept_no  = d.get("rcept_no", "")
        corp_name = d.get("corp_name", "?")
        report_nm = d.get("report_nm", "?")
        signal, summary = _summarize(corp_name, report_nm)
        save_dart_summary(rcept_no, corp_name, report_nm, signal, summary)
        results.append({"corp_name": corp_name, "signal": signal, "summary": summary})
        logger.info(f"[dart_summarizer] {corp_name}: {signal} — {summary}")

    if send_kakao and results:
        lines = [f"📢 공시 요약 ({now.strftime('%H:%M')})", "─" * 20]
        for r in results:
            emoji = SIGNAL_EMOJI.get(r["signal"], "⚪")
            lines.append(f"{emoji} {r['corp_name']}: {r['summary']}")
        msg = "\n".join(lines)[:950]
        try:
            from notify.send import send_message_to_self
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/dart_alert", ai_generated=True)
            logger.info(f"[dart_summarizer] 카카오톡 발송 완료 ({len(results)}건)")
        except Exception as e:
            logger.warning(f"[dart_summarizer] 카카오톡 발송 실패: {e}")

    return {"ok": True, "summarized": len(results)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run())
