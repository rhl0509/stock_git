"""
agent/earnings_monitor.py
==========================
실적 모니터링 에이전트.
DART에서 분기·반기·사업보고서 제출을 감지하고 LLM이 핵심 실적을 요약해 발송.
어닝서프라이즈/쇼크가 있을 때만 카카오 발송 (실적중립은 로그만).

스케줄: 평일 17:00 (공시 집중 제출 후)
수동:   python -m agent.earnings_monitor
"""
from __future__ import annotations

import logging
from datetime import datetime

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate
from agent.store import is_dart_summarized, save_dart_summary

logger = logging.getLogger(__name__)

EARNINGS_KEYWORDS = ["사업보고서", "분기보고서", "반기보고서"]
EARNINGS_EMOJI    = {"어닝서프라이즈": "🚀", "어닝쇼크": "💥", "실적중립": "📋"}


def _get_earnings_disclosures() -> list[dict]:
    try:
        from XGBoost_v2.dart_client import get_market_disclosures
        all_disc = get_market_disclosures(days=1) or []
        return [d for d in all_disc if any(kw in d.get("report_nm", "") for kw in EARNINGS_KEYWORDS)]
    except Exception as e:
        logger.warning(f"[earnings_monitor] 공시 수집 실패: {e}")
        return []


def _analyze(corp_name: str, report_nm: str) -> dict:
    prompt = f"""실적 공시 분석:
회사: {corp_name}
보고서: {report_nm}

형식:
신호: [어닝서프라이즈/어닝쇼크/실적중립]
요약: [30자 이내]
메모: [투자자 주목 포인트 1줄]

공시 제목만으로 판단 어려우면 신호=실적중립, 요약=원문 확인 필요."""

    result = generate(prompt, temperature=0.2, max_tokens=150)
    out = {"signal": "실적중립", "summary": report_nm[:60], "memo": ""}

    if result:
        for line in result.strip().split("\n"):
            line = line.strip()
            if line.startswith("신호:"):
                for s in ("어닝서프라이즈", "어닝쇼크", "실적중립"):
                    if s in line:
                        out["signal"] = s
                        break
            elif line.startswith("요약:"):
                out["summary"] = line[3:].strip()[:60]
            elif line.startswith("메모:"):
                out["memo"] = line[3:].strip()[:80]
    return out


def run(send_kakao: bool = True) -> dict:
    now = datetime.now()
    if now.weekday() >= 5:
        logger.info("[earnings_monitor] 주말 — 스킵")
        return {"ok": True, "skipped": True}

    logger.info("[earnings_monitor] 실적 공시 감지 시작")
    disclosures = _get_earnings_disclosures()
    new_ones    = [d for d in disclosures if not is_dart_summarized(d.get("rcept_no", ""))]

    if not new_ones:
        logger.info("[earnings_monitor] 새로운 실적 공시 없음")
        return {"ok": True, "analyzed": 0}

    results = []
    for d in new_ones[:8]:
        corp_name = d.get("corp_name", "?")
        report_nm = d.get("report_nm", "?")
        rcept_no  = d.get("rcept_no", "")
        analysis  = _analyze(corp_name, report_nm)
        save_dart_summary(rcept_no, corp_name, report_nm, analysis["signal"], analysis["summary"])
        results.append({"corp_name": corp_name, **analysis})
        logger.info(f"[earnings_monitor] {corp_name}: {analysis['signal']}")

    notable = [r for r in results if r["signal"] in ("어닝서프라이즈", "어닝쇼크")]
    if not notable:
        logger.info("[earnings_monitor] 서프라이즈/쇼크 없음 — 발송 스킵")
        return {"ok": True, "analyzed": len(results), "notable": 0}

    lines = [f"📊 실적 알림 ({now.strftime('%m/%d')})", "─" * 20]
    for r in notable:
        emoji = EARNINGS_EMOJI.get(r["signal"], "📋")
        lines.append(f"{emoji} {r['corp_name']}: {r['summary']}")
        if r.get("memo"):
            lines.append(f"   └ {r['memo']}")
    msg = "\n".join(lines)[:950]

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/market_reports", ai_generated=True)
            logger.info(f"[earnings_monitor] 카카오톡 발송 완료 ({len(notable)}건)")
        except Exception as e:
            logger.warning(f"[earnings_monitor] 카카오톡 발송 실패: {e}")

    return {"ok": True, "analyzed": len(results), "notable": len(notable)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run())
