"""
agent/report_performance.py
============================
ML 추천 성과 추적 에이전트.

흐름:
  1. 오늘 daily_recommend.json 읽기 → recommend_track 테이블에 진입가 스냅샷 저장
  2. target_days 경과한 미평가 항목 조회 → yfinance로 현재가 확인 → 수익률 계산
  3. LLM 성과 분석 → 카카오톡 발송

스케줄: 평일 09:30
수동: python -m agent.report_performance
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import yfinance as yf

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate

logger = logging.getLogger(__name__)

ROOT           = Path(__file__).parent.parent
RECOMMEND_JSON = ROOT / "XGBoost_v2" / "model" / "daily_recommend.json"

TYPE_TARGET_DAYS = {"daily": 3, "short": 5, "swing": 14}


# ─────────────────────────────────────────────────────────────────
# DB 헬퍼
# ─────────────────────────────────────────────────────────────────

def _upsert_entry(code: str, name: str, rec_type: str, rec_date: str, confidence: float, entry_price: float):
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recommend_track
                    (code, name, recommend_type, recommend_date, confidence, entry_price, target_days)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE entry_price=VALUES(entry_price)
                """,
                (code, name, rec_type, rec_date, confidence,
                 entry_price, TYPE_TARGET_DAYS[rec_type]),
            )
        conn.commit()
    finally:
        conn.close()


def _get_pending(as_of: str) -> list[dict]:
    """만기됐지만 아직 미평가된 항목."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM recommend_track
                WHERE exit_price IS NULL
                  AND DATE_ADD(recommend_date, INTERVAL target_days DAY) <= %s
                """,
                (as_of,),
            )
            return cur.fetchall() or []
    finally:
        conn.close()


def _save_result(row_id: int, exit_price: float, return_pct: float):
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE recommend_track SET exit_price=%s, return_pct=%s, evaluated_at=NOW() WHERE id=%s",
                (exit_price, return_pct, row_id),
            )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# 가격 조회
# ─────────────────────────────────────────────────────────────────

def _get_current_price(code: str) -> float | None:
    for suffix in (".KS", ".KQ"):
        try:
            df = yf.download(code + suffix, period="3d", progress=False, auto_adjust=True)
            if not df.empty:
                closes = df["Close"].dropna()
                if len(closes) >= 1:
                    return float(closes.iloc[-1])
        except Exception:
            continue
    logger.warning(f"[performance] 가격 조회 실패: {code}")
    return None


# ─────────────────────────────────────────────────────────────────
# 핵심 로직
# ─────────────────────────────────────────────────────────────────

def _record_today_entries():
    """오늘 추천 종목을 진입가와 함께 DB에 저장."""
    if not RECOMMEND_JSON.exists():
        logger.warning("[performance] daily_recommend.json 없음")
        return
    try:
        rec = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[performance] JSON 파싱 실패: {e}")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    for rec_type in ("daily", "short", "swing"):
        for item in rec.get(rec_type, []):
            code = item.get("code", "")
            name = item.get("name", code)
            conf = float(item.get("confidence", 0.0))
            if not code:
                continue
            price = _get_current_price(code)
            if price:
                _upsert_entry(code, name, rec_type, today, conf, price)
                logger.info(f"[performance] 진입 기록: {name}({code}) [{rec_type}] @ {price:,.0f}")


def _evaluate_matured() -> list[dict]:
    """만기 항목 수익률 계산 후 DB 저장, 결과 반환."""
    today   = datetime.now().strftime("%Y-%m-%d")
    pending = _get_pending(today)
    results = []
    for row in pending:
        exit_price = _get_current_price(row["code"])
        if not exit_price or not row.get("entry_price"):
            continue
        ret = (exit_price / float(row["entry_price"]) - 1) * 100
        _save_result(row["id"], exit_price, ret)
        results.append({**dict(row), "exit_price": exit_price, "return_pct": ret})
        logger.info(f"[performance] 평가: {row['name']}({row['code']}) {ret:+.2f}%")
    return results


def _build_llm_prompt(results: list[dict]) -> str:
    lines = []
    for r in results:
        hit = "✅" if r["return_pct"] >= 0 else "❌"
        lines.append(
            f"  {hit} {r['name']}({r['code']}) [{r['recommend_type']}] "
            f"{r['return_pct']:+.2f}% (진입 {r['entry_price']:,.0f} → 현재 {r['exit_price']:,.0f})"
        )
    win  = sum(1 for r in results if r["return_pct"] >= 0)
    total = len(results)
    return f"""ML 모델 추천 종목 실제 성과:

{"".join(l + chr(10) for l in lines)}
총 {total}건 | 승률 {win/total*100:.1f}% ({win}승 {total-win}패)

4문장 이내로:
1. 전반적 성과 평가
2. 패턴이 보이면 한 줄
3. 시장 상황 연관성 한 줄"""


def run(send_kakao: bool = True) -> dict:
    logger.info("[report_performance] 시작")
    _record_today_entries()
    results = _evaluate_matured()

    if not results:
        logger.info("[report_performance] 평가할 만기 항목 없음")
        return {"ok": True, "evaluated": 0}

    win_rate = sum(1 for r in results if r["return_pct"] >= 0) / len(results) * 100
    analysis = generate(_build_llm_prompt(results), temperature=0.2, max_tokens=400)

    lines = ["📊 ML 추천 성과 리포트", "─" * 20]
    for r in results:
        arrow = "▲" if r["return_pct"] >= 0 else "▼"
        lines.append(f"{r['name']} [{r['recommend_type']}] {arrow}{abs(r['return_pct']):.2f}%")
    lines += ["", f"승률 {win_rate:.1f}% ({len(results)}건)"]
    if analysis:
        lines += ["", analysis[:300]]
    msg = "\n".join(lines)[:950]

    if send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/market_reports", ai_generated=True)
            logger.info("[report_performance] 카카오톡 발송 완료")
        except Exception as e:
            logger.warning(f"[report_performance] 카카오톡 발송 실패: {e}")

    return {"ok": True, "evaluated": len(results), "win_rate": round(win_rate, 1)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run())
