"""
agent/auto_stop_alert.py
========================
보유종목 손절/목표가 자동 등록 에이전트.

AI 추천(daily_recommend + 최근 14일 이력)에 들어 있는 stop/target 가격을,
실제로 보유 중인 종목에 한해 price_alerts에 자동 등록한다.
→ 가격 도달 시 기존 price_alert 체크 잡(10분 주기)이 카톡 발송.

원칙:
  - 수동 등록 알림은 절대 건드리지 않음 (note가 'AI자동'으로 시작하는 행만 관리)
  - 더 이상 보유하지 않는 종목의 AI자동 알림은 비활성화
  - 같은 종목이 여러 카테고리에 있으면 최신 추천 우선

스케줄: 평일 15:55 (키움 동기화 15:50 직후)
수동:   python -m agent.auto_stop_alert
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5001")
ROOT        = Path(__file__).parent.parent
MODEL_DIR   = ROOT / "XGBoost_v2" / "model"
HISTORY_DIR = MODEL_DIR / "recommend_history"
NOTE_PREFIX = "AI자동"
LOOKBACK_DAYS = 14


def _load_recommend_map() -> dict:
    """최근 추천에서 code → {stop, target, rtype, date} (최신 우선)."""
    rec_map: dict = {}

    def _ingest(data: dict, date_str: str):
        for rtype in ("triple", "daily", "short", "swing"):
            for s in (data.get(rtype) or []):
                code = str(s.get("code", "")).zfill(6)
                if not code.isdigit() or not s.get("stop"):
                    continue
                # 이미 더 최신 추천이 있으면 유지
                if code in rec_map and rec_map[code]["date"] >= date_str:
                    continue
                rec_map[code] = {
                    "stop":   int(s["stop"]),
                    "target": int(s.get("target") or 0) or None,
                    "rtype":  rtype,
                    "date":   date_str,
                }

    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    if HISTORY_DIR.exists():
        for p in sorted(HISTORY_DIR.glob("*.json")):
            if p.stem >= cutoff:
                try:
                    _ingest(json.loads(p.read_text(encoding="utf-8")), p.stem)
                except Exception:
                    continue
    cur = MODEL_DIR / "daily_recommend.json"
    if cur.exists():
        try:
            data = json.loads(cur.read_text(encoding="utf-8"))
            _ingest(data, datetime.now().strftime("%Y%m%d"))
        except Exception:
            pass
    return rec_map


def run(send_kakao: bool = True) -> dict:
    from auto_jobs import get_owner_user_no
    from database.db_connection import get_db_connection

    user_no = get_owner_user_no()
    if not user_no:
        return {"ok": True, "skipped": True, "reason": "대상 사용자 없음"}

    rec_map = _load_recommend_map()
    if not rec_map:
        logger.info("[auto_stop] 추천 데이터 없음")
        return {"ok": True, "skipped": True, "reason": "추천 데이터 없음"}

    conn = get_db_connection()
    created, updated, deactivated = [], [], []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, name, quantity FROM stock_holdings "
                        "WHERE member_id=%s AND quantity > 0", (user_no,))
            holdings = {r['code'].zfill(6): r['name'] for r in cur.fetchall()}

            # 기존 AI자동 알림
            cur.execute("SELECT id, code, target_price, stop_price, active FROM price_alerts "
                        "WHERE user_no=%s AND note LIKE %s", (user_no, NOTE_PREFIX + '%'))
            existing = {r['code'].zfill(6): r for r in cur.fetchall()}

            # 보유 ∩ 추천 → 등록/갱신
            for code, name in holdings.items():
                rec = rec_map.get(code)
                if not rec:
                    continue
                note = f"{NOTE_PREFIX} {rec['rtype']} {rec['date'][:4]}-{rec['date'][4:6]}-{rec['date'][6:]}"
                ex = existing.get(code)
                if ex:
                    if (ex['stop_price'] != rec['stop'] or ex['target_price'] != rec['target']
                            or not ex['active']):
                        cur.execute(
                            "UPDATE price_alerts SET target_price=%s, stop_price=%s, "
                            "note=%s, active=1 WHERE id=%s",
                            (rec['target'], rec['stop'], note, ex['id']))
                        updated.append(f"{name}: 손절 {rec['stop']:,} / 목표 {rec['target']:,}" if rec['target']
                                       else f"{name}: 손절 {rec['stop']:,}")
                else:
                    cur.execute(
                        "INSERT INTO price_alerts (user_no, code, name, target_price, stop_price, note) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (user_no, code, name, rec['target'], rec['stop'], note))
                    created.append(f"{name}: 손절 {rec['stop']:,}" +
                                   (f" / 목표 {rec['target']:,}" if rec['target'] else ""))

            # 미보유 종목의 AI자동 알림 비활성화
            for code, ex in existing.items():
                if code not in holdings and ex['active']:
                    cur.execute("UPDATE price_alerts SET active=0 WHERE id=%s", (ex['id'],))
                    deactivated.append(code)
        conn.commit()
    finally:
        conn.close()

    changed = len(created) + len(updated)
    if changed and send_kakao:
        from notify.send import send_message_to_self
        lines = [f"· 신규 {c}" for c in created[:6]] + [f"· 갱신 {u}" for u in updated[:6]]
        msg = ("🛡 손절/목표가 자동 등록\n" + "\n".join(lines)
               + (f"\n· 미보유 {len(deactivated)}종목 알림 해제" if deactivated else "")
               + "\n도달 시 자동 알림됩니다.")
        send_message_to_self(msg, link_url=f"{APP_BASE_URL}/price_alert", ai_generated=True)

    logger.info(f"[auto_stop] 신규 {len(created)} 갱신 {len(updated)} 해제 {len(deactivated)}")
    return {"ok": True, "created": len(created), "updated": len(updated),
            "deactivated": len(deactivated)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
