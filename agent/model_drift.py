"""
agent/model_drift.py
====================
모델 드리프트 감시 에이전트 — "AI를 감시하는 AI".

recommend_track의 실현 적중률(최근 30일)을 학습 시점 CV 기준선(train_report_v2.json)과
비교해, 모델 성능이 조용히 망가지는 것을 감지한다.

판정:
  - 평가 표본 < MIN_SAMPLES → 데이터 부족, 로그만
  - 적중률 < cv_acc - DRIFT_THRESHOLD → 드리프트 경보 (카톡)
  - 평균 수익률 < 0 → 추가 경고

스케줄: 매주 월요일 09:05
수동:   python -m agent.model_drift
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5001")
ROOT = Path(__file__).parent.parent
TRAIN_REPORT = ROOT / "XGBoost_v2" / "model" / "train_report_v2.json"

MIN_SAMPLES     = 20     # 유형별 최소 평가 표본
LOOKBACK_DAYS   = 30
DRIFT_THRESHOLD = 0.10   # 기준선 대비 -10%p 이상이면 드리프트


def _load_baselines() -> dict:
    """{recommend_type: cv_acc}"""
    try:
        tr = json.loads(TRAIN_REPORT.read_text(encoding="utf-8"))
        return {k: v.get("cv_acc") for k, v in (tr.get("labels") or {}).items()
                if v.get("cv_acc") is not None}
    except Exception as e:
        logger.warning(f"[drift] train_report 로드 실패: {e}")
        return {}


def _realized_stats() -> list[dict]:
    """recommend_track에서 최근 30일 평가 완료분 유형별 집계."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT recommend_type AS rtype,
                       COUNT(*)                            AS n,
                       AVG(return_pct)                     AS avg_ret,
                       SUM(return_pct > 0) / COUNT(*)      AS hit_rate
                FROM recommend_track
                WHERE evaluated_at IS NOT NULL
                  AND recommend_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY recommend_type
            """, (LOOKBACK_DAYS,))
            return cur.fetchall()
    finally:
        conn.close()


def run(send_kakao: bool = True) -> dict:
    baselines = _load_baselines()
    stats     = _realized_stats()

    if not stats:
        logger.info("[drift] 평가 완료된 추천 없음 — 데이터 축적 대기")
        return {"ok": True, "skipped": True, "reason": "평가 데이터 없음"}

    drifts, healthy, insufficient = [], [], []
    for s in stats:
        rtype, n = s['rtype'], int(s['n'])
        hit  = float(s['hit_rate'] or 0)
        aret = float(s['avg_ret'] or 0)
        base = baselines.get(rtype)
        if n < MIN_SAMPLES:
            insufficient.append(f"{rtype}: 표본 {n}건 (최소 {MIN_SAMPLES})")
            continue
        line = f"{rtype}: 적중률 {hit:.1%} (기준 {base:.1%}) · 평균 {aret:+.2f}% · {n}건" \
            if base is not None else f"{rtype}: 적중률 {hit:.1%} · 평균 {aret:+.2f}% · {n}건"
        is_drift = (base is not None and hit < base - DRIFT_THRESHOLD)
        if aret < 0:
            line += " ⚠손실"
            is_drift = True
        (drifts if is_drift else healthy).append(line)

    if drifts and send_kakao:
        from notify.send import send_message_to_self
        msg = ("🔻 ML 모델 성능 저하 감지\n"
               + "\n".join(f"· {d}" for d in drifts)
               + ("\n\n[정상]\n" + "\n".join(f"· {h}" for h in healthy) if healthy else "")
               + "\n\n→ 추천 신뢰도 하향 권고 · 재학습/피처 점검 필요")
        send_message_to_self(msg, link_url=f"{APP_BASE_URL}/stock_ai_performance",
                             ai_generated=True)

    summary = f"드리프트 {len(drifts)} | 정상 {len(healthy)} | 표본부족 {len(insufficient)}"
    logger.info(f"[drift] {summary}")
    if insufficient:
        logger.info(f"[drift] 표본 부족: {insufficient}")
    return {"ok": True, "drifts": drifts, "healthy": healthy,
            "insufficient": insufficient}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
