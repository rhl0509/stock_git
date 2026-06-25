"""
agent/report_monthly.py
========================
월간 시장 보고서 생성 및 저장/발송. 매월 마지막 영업일 20:00 실행.

  python -m agent.report_monthly
"""
from __future__ import annotations

import logging
from datetime import datetime

from agent.data_collector import APP_BASE_URL, collect_monthly
from agent.llm_client import generate
from agent.store import get_report_by_date, save_report

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 한국 경제 및 금융 시장 전문 애널리스트입니다.
제공된 월간 데이터를 바탕으로 심층적인 월간 시장 분석 보고서를 작성합니다.
매수/매도 의견은 절대 제시하지 않습니다.
거시경제 흐름, 시장 구조 변화, 섹터 로테이션 등을 분석하고
다음 달 시장 환경 변수를 체계적으로 정리합니다.
한국어로 작성하며, 심층 분석적이고 전문적인 문체를 사용합니다."""


def _build_prompt(data: dict) -> str:
    macro   = data.get("macro", {})
    glb     = data.get("global", {})
    markets = data.get("markets", {})
    sectors = data.get("sectors", [])
    disc    = data.get("disclosures", [])
    paper   = data.get("paper_trading", {})
    news    = data.get("news", {})
    month   = data.get("month", datetime.now().strftime("%Y년 %m월"))
    date    = data.get("date", datetime.now().strftime("%Y-%m-%d"))

    # 국내 시장 월간
    mkt_lines = []
    for name, info in markets.items():
        period_chg = info.get("period_change_pct")
        cur        = info.get("current")
        cur_str    = f"{cur:,.2f}" if isinstance(cur, (int, float)) else "-"
        if period_chg is not None:
            arrow = "▲" if period_chg >= 0 else "▼"
            mkt_lines.append(f"  - {name}: {cur_str} (월간 {arrow}{abs(period_chg):.2f}%)")
    mkt_str = "\n".join(mkt_lines) if mkt_lines else "  - 데이터 없음"

    # 섹터 전체 목록
    sector_lines = [
        f"  - {s['sector']}: {s['return_pct']:+.2f}%"
        for s in sorted(sectors, key=lambda x: x["return_pct"], reverse=True)
    ]
    sector_str = "\n".join(sector_lines) if sector_lines else "  - 섹터 데이터 없음"

    # 글로벌
    sp500_ret  = glb.get("sp500_ret_5d", glb.get("sp500_ret_1d", 0)) * 100
    vix        = glb.get("vix_level", 0)
    oil_ret    = glb.get("oil_ret_20d", 0) * 100
    us_10y     = glb.get("us_10y", 0)

    # 거시
    usdkrw    = macro.get("usdkrw", "-")
    call_rate = macro.get("call_rate", "-")
    bond_3y   = macro.get("bond_3y", "-")
    cpi       = macro.get("cpi", "-")

    # 공시 요약
    disc_lines = [f"  - {d.get('corp_name','?')}: {d.get('report_nm','?')}" for d in disc[:10]]
    disc_str = "\n".join(disc_lines) if disc_lines else "  - 주요 공시 없음"

    # 가상매매 성과
    if paper:
        win_rate  = paper.get("win_rate", 0)
        avg_ret   = paper.get("avg_net_return", paper.get("avg_return", 0))
        total     = paper.get("total_trades", 0)
        paper_str = f"  - 총 거래: {total}건, 승률: {win_rate:.1f}%, 평균수익률: {avg_ret:+.2f}%"
    else:
        paper_str = "  - 가상매매 데이터 없음"

    prompt = f"""아래는 {month} 국내외 금융 시장 월간 데이터입니다.

=== 국내 시장 월간 성과 ===
{mkt_str}

=== 섹터별 월간 수익률 (전체) ===
{sector_str}

=== 글로벌 시장 ===
  - S&P500 최근 5거래일 수익률: {sp500_ret:+.2f}%
  - VIX (월 종가): {vix:.1f}
  - 유가 20일 추이: {oil_ret:+.2f}%
  - 미국 10년물 금리: {us_10y:.2f}%

=== 거시지표 (월 종가) ===
  - 원/달러: {usdkrw}
  - 콜금리: {call_rate}%
  - 국고채 3년: {bond_3y}%
  - CPI: {cpi}

=== 이달 주요 공시 (상위 10건) ===
{disc_str}

=== ML 가상매매 월간 성과 ===
{paper_str}

---

위 데이터를 종합해 {month} 월간 시장 보고서를 아래 형식으로 작성해주세요:

## {month} 월간 시장 보고서

### 이달 시장 총평
(KOSPI/KOSDAQ 월간 흐름과 주요 특징 4-5문장)

### 거시경제 분석
(환율, 금리, CPI 등 거시지표 변화와 시장 영향 분석 4-5문장)

### 글로벌 시장과의 상관관계
(미국 시장, VIX, 원자재 등 글로벌 변수 분석 3-4문장)

### 섹터별 월간 동향
(강세/약세 섹터의 배경과 원인 분석 4-5문장)

### 이달 주요 이슈 및 공시
(시장에 영향을 준 주요 공시/이슈 정리)

### ML 모델 검증 성과
(가상매매 결과를 통한 모델 예측력 평가)

### 다음 달 시장 환경 변수
(다음 달 주시해야 할 거시/정책/이벤트 변수 5가지 이상)

### 월간 시장 구조 평가
(이달 시장의 전반적 특성과 투자 환경 평가 2-3문장)
"""
    return prompt


def _build_summary(content: str, month: str) -> str:
    header = f"📋 {month} 월간 시장 보고서\n{'─'*20}\n"
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    return (header + "\n".join(lines[:40]))[:950]


def run(send_kakao: bool = True) -> dict:
    """월간 보고서 생성 → DB 저장 → 카카오톡 발송."""
    today = datetime.now()
    # 월간 보고서는 해당 월의 1일을 키로 사용
    report_date = today.strftime("%Y-%m-01")
    month_str   = today.strftime("%Y년 %m월")
    logger.info(f"[report_monthly] 시작: {month_str}")

    existing = get_report_by_date("monthly", report_date)
    if existing:
        logger.info("[report_monthly] 이달 보고서 이미 존재, 스킵")
        return {"ok": True, "skipped": True, "id": existing["id"]}

    data = collect_monthly()

    prompt = _build_prompt(data)
    logger.info("[report_monthly] LLM 보고서 생성 중...")
    content = generate(prompt, system=SYSTEM_PROMPT, temperature=0.35, max_tokens=4096)
    if not content:
        logger.error("[report_monthly] LLM 생성 실패")
        return {"ok": False, "error": "LLM 생성 실패"}

    title   = f"{month_str} 월간 시장 보고서"
    summary = _build_summary(content, month_str)

    report_id = save_report(
        report_type="monthly",
        report_date=report_date,
        title=title,
        content=content,
        summary=summary,
    )
    logger.info(f"[report_monthly] DB 저장 완료: id={report_id}")

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(
                summary,
                link_url=f"{APP_BASE_URL}/reports",
                ai_generated=True,
            )
            logger.info("[report_monthly] 카카오톡 발송 완료")
        except Exception as e:
            logger.warning(f"[report_monthly] 카카오톡 발송 실패: {e}")

    return {"ok": True, "id": report_id, "title": title}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    result = run()
    print(result)
