"""
routes/agent_dashboard.py
==========================
에이전트 모니터 대시보드 API.

GET  /api/agent/status           — 스케줄 현황 + 최근 실행 이력 포함
GET  /api/agent/performance      — 추천 성과 추적 최근 데이터
GET  /api/agent/dart             — 공시 요약 최근 내역
GET  /api/agent/events           — 경제 이벤트 캘린더
GET  /api/agent/run-log          — 잡 실행 이력
GET  /api/agent/anomaly          — 이상 감지 결과
GET  /api/agent/feed             — 통합 에이전트 피드 (타임라인)
GET  /api/agent/notify-settings  — 잡별 알림 채널 설정 조회
POST /api/agent/notify-settings  — 잡별 알림 채널 설정 저장
POST /api/agent/run              — 특정 잡 즉시 실행 (백그라운드)
POST /api/agent/events           — 이벤트 캘린더 항목 수동 추가
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Body, Depends
from fastapi.responses import JSONResponse
from routes.utils import get_login_user, login_required_response, require_login_smart

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_login_smart)], prefix="/api/agent", tags=["agent"])

# ─────────────────────────────────────────────────────────────────
# 잡 메타 (프론트 표시용)
# ─────────────────────────────────────────────────────────────────
JOB_META: dict[str, dict] = {
    "report_daily":      {"name": "일간 보고서",       "icon": "bi-calendar-day",        "group": "report"},
    "report_weekly":     {"name": "주간 보고서",       "icon": "bi-calendar-week",       "group": "report"},
    "report_monthly":    {"name": "월간 보고서",       "icon": "bi-calendar-month",      "group": "report"},
    "agent_performance": {"name": "추천 성과 추적",    "icon": "bi-graph-up",            "group": "agent"},
    "agent_anomaly":     {"name": "이상 감지",         "icon": "bi-exclamation-triangle","group": "agent"},
    "agent_events":      {"name": "경제 이벤트 알림",  "icon": "bi-calendar-event",      "group": "agent"},
    "agent_dart":        {"name": "공시 요약",         "icon": "bi-file-earmark-text",   "group": "agent"},
    "agent_flow":        {"name": "외국인·기관 수급",  "icon": "bi-currency-dollar",     "group": "agent"},
    "agent_earnings":    {"name": "실적 모니터링",     "icon": "bi-bar-chart-line",      "group": "agent"},
    "agent_rebalance":   {"name": "리밸런싱 알림",     "icon": "bi-arrow-repeat",        "group": "agent"},
}

# ─────────────────────────────────────────────────────────────────
# 잡 실행 함수 맵 (수동 실행 — send_kakao=False)
# ─────────────────────────────────────────────────────────────────
def _get_runner(job_id: str):
    runners = {
        "report_daily":      lambda: __import__("agent.report_daily",      fromlist=["run"]).run(send_kakao=False),
        "report_weekly":     lambda: __import__("agent.report_weekly",     fromlist=["run"]).run(send_kakao=False),
        "report_monthly":    lambda: __import__("agent.report_monthly",    fromlist=["run"]).run(send_kakao=False),
        "agent_performance": lambda: __import__("agent.report_performance",fromlist=["run"]).run(send_kakao=False),
        "agent_anomaly":     lambda: __import__("agent.anomaly_detector",  fromlist=["run"]).run(send_kakao=False),
        "agent_events":      lambda: __import__("agent.event_calendar",    fromlist=["run"]).run(send_kakao=False),
        "agent_dart":        lambda: __import__("agent.dart_summarizer",   fromlist=["run"]).run(send_kakao=False),
        "agent_flow":        lambda: __import__("agent.flow_monitor",      fromlist=["run"]).run(send_kakao=False),
        "agent_earnings":    lambda: __import__("agent.earnings_monitor",  fromlist=["run"]).run(send_kakao=False),
        "agent_rebalance":   lambda: __import__("agent.rebalance_alert",   fromlist=["run"]).run(send_kakao=False),
    }
    return runners.get(job_id)


# ─────────────────────────────────────────────────────────────────
# 직렬화 헬퍼
# ─────────────────────────────────────────────────────────────────
def _ser(row: dict) -> dict:
    from decimal import Decimal
    return {
        k: (v.isoformat() if hasattr(v, "isoformat")
            else float(v) if isinstance(v, Decimal)
            else v)
        for k, v in row.items()
    }


# ─────────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────────

@router.get("/status")
def api_status():
    """스케줄러 잡 현황 + 최근 실행 이력."""
    try:
        from agent.scheduler import get_status, get_run_log
        jobs = {j["id"]: j for j in get_status()}
        # 잡별 가장 최근 실행 기록 추출
        all_logs = get_run_log(limit=len(JOB_META) * 3)
        log_map: dict[str, dict] = {}
        for log in all_logs:
            if log["job_id"] not in log_map:
                log_map[log["job_id"]] = log
    except Exception:
        jobs   = {}
        log_map = {}

    result = []
    for job_id, meta in JOB_META.items():
        job  = jobs.get(job_id, {})
        last = log_map.get(job_id, {})
        result.append({
            "id":           job_id,
            "name":         meta["name"],
            "icon":         meta["icon"],
            "group":        meta["group"],
            "next_run":     job.get("next_run", "-"),
            "last_run_at":  last.get("started_at"),
            "last_status":  last.get("status"),
            "last_summary": last.get("summary"),
        })
    return JSONResponse({"ok": True, "jobs": result})


@router.post("/run")
def api_run(
    request: Request,
    background_tasks: BackgroundTasks,
    job_id: str = Query(...),
):
    if not get_login_user(request):
        return login_required_response()

    runner = _get_runner(job_id)
    if not runner:
        raise HTTPException(status_code=400, detail=f"알 수 없는 잡: {job_id}")

    def _bg():
        try:
            from agent.scheduler import run_and_log
            run_and_log(job_id, runner, triggered_by='manual')
        except Exception as e:
            logger.error(f"[agent_dashboard] 수동 실행 실패 [{job_id}]: {e}", exc_info=True)

    background_tasks.add_task(_bg)
    name = JOB_META.get(job_id, {}).get("name", job_id)
    return JSONResponse({"ok": True, "message": f"'{name}' 실행 시작 (백그라운드)"})


@router.get("/performance")
def api_performance(limit: int = Query(30, ge=1, le=100)):
    """추천 성과 추적 최근 데이터."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM recommend_track ORDER BY recommend_date DESC, id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall() or []
        return JSONResponse({"ok": True, "data": [_ser(r) for r in rows]})
    except Exception as e:
        logger.error(f"[agent/performance] {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": "서버 오류가 발생했습니다."})
    finally:
        conn.close()


@router.get("/dart")
def api_dart(limit: int = Query(20, ge=1, le=100)):
    """공시 요약 최근 내역."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM dart_summaries ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall() or []
        return JSONResponse({"ok": True, "data": [_ser(r) for r in rows]})
    except Exception as e:
        logger.error(f"[agent/dart] {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": "서버 오류가 발생했습니다."})
    finally:
        conn.close()


@router.get("/events")
def api_events(upcoming_only: bool = Query(False)):
    """경제 이벤트 캘린더."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if upcoming_only:
                cur.execute(
                    "SELECT * FROM event_calendar WHERE event_date >= CURDATE() ORDER BY event_date ASC LIMIT 30"
                )
            else:
                cur.execute(
                    "SELECT * FROM event_calendar ORDER BY event_date ASC LIMIT 100"
                )
            rows = cur.fetchall() or []
        return JSONResponse({"ok": True, "events": [_ser(r) for r in rows]})
    except Exception as e:
        logger.error(f"[agent/events] {e}", exc_info=True)
        return JSONResponse({"ok": False, "events": [], "error": "서버 오류가 발생했습니다."})
    finally:
        conn.close()


@router.post("/events")
def add_event(request: Request, body: dict = Body(default={})):
    """이벤트 캘린더 항목 수동 추가."""
    if not get_login_user(request):
        return login_required_response()
    from database.db_connection import get_db_connection
    if not body.get('event_date') or not body.get('title'):
        return JSONResponse({"ok": False, "error": "event_date와 title은 필수입니다."}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO event_calendar (event_date, event_type, title, importance, country, notified)
                VALUES (%s, %s, %s, %s, %s, 0)
            """, (body.get('event_date'), body.get('event_type', 'earnings'),
                  body.get('title', ''), body.get('importance', 'medium'), body.get('country', 'KR')))
            conn.commit()
        return JSONResponse({"ok": True, "id": cur.lastrowid})
    except Exception as e:
        logger.error(f"[agent/events/add] {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


@router.get("/run-log")
def api_run_log(
    job_id: str = Query(None),
    limit:  int = Query(50, ge=1, le=200),
):
    """잡 실행 이력."""
    try:
        from agent.scheduler import get_run_log
        return JSONResponse({"ok": True, "logs": get_run_log(job_id, limit)})
    except Exception as e:
        logger.error(f"[agent/run-log] {e}", exc_info=True)
        return JSONResponse({"ok": False, "logs": [], "error": "서버 오류가 발생했습니다."})


@router.get("/anomaly")
def api_anomaly(limit: int = Query(30, ge=1, le=100)):
    """이상 감지 결과."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM agent_anomaly_results ORDER BY detected_at DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall() or []
        return JSONResponse({"ok": True, "data": [_ser(r) for r in rows]})
    except Exception as e:
        logger.error(f"[agent/anomaly] {e}", exc_info=True)
        return JSONResponse({"ok": False, "data": [], "error": "서버 오류가 발생했습니다."})
    finally:
        conn.close()


@router.get("/feed")
def api_feed(limit: int = Query(30, ge=1, le=50)):
    """통합 에이전트 피드 — 최근 활동 타임라인."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    items: list[dict] = []

    def _safe_query(sql: str, params=None) -> list[dict]:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [_ser(r) for r in (cur.fetchall() or [])]
        except Exception as ex:
            logger.debug(f"[agent/feed] 쿼리 스킵: {ex}")
            return []

    try:
        items += _safe_query("""
            SELECT id, started_at AS ts, job_id, status, summary, error_msg, 'run' AS type
            FROM agent_run_log
            WHERE status IN ('success','failed')
            ORDER BY started_at DESC LIMIT 15
        """)
        items += _safe_query("""
            SELECT id, created_at AS ts, corp_name AS title, `signal`, summary, rcept_no, 'dart' AS type
            FROM dart_summaries
            ORDER BY created_at DESC LIMIT 10
        """)
        items += _safe_query("""
            SELECT id, detected_at AS ts, name AS title, signals, price_chg,
                   vol_ratio, explanation, 'anomaly' AS type
            FROM agent_anomaly_results
            ORDER BY detected_at DESC LIMIT 10
        """)
        items += _safe_query("""
            SELECT id, event_date AS ts, title, event_type, importance, 'event' AS type
            FROM event_calendar
            WHERE event_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
              AND event_date <= DATE_ADD(CURDATE(), INTERVAL 7 DAY)
            ORDER BY event_date DESC LIMIT 10
        """)
    finally:
        conn.close()

    items.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    return JSONResponse({"ok": True, "items": items[:limit]})


@router.get("/notify-settings")
def api_notify_settings():
    """잡별 알림 채널 설정 조회. 미설정 잡은 기본값(kakao=True, email=False)으로 채움."""
    try:
        from agent.scheduler import get_notify_settings
        rows = get_notify_settings()
        settings_map: dict[tuple, bool] = {(r['job_id'], r['channel']): bool(r['enabled']) for r in rows}
        result = {}
        for job_id in JOB_META:
            result[job_id] = {
                'kakao': settings_map.get((job_id, 'kakao'), True),
                'email': settings_map.get((job_id, 'email'), False),
            }
        return JSONResponse({"ok": True, "settings": result})
    except Exception as e:
        logger.error(f"[agent/notify-settings] {e}", exc_info=True)
        return JSONResponse({"ok": False, "settings": {}, "error": "서버 오류가 발생했습니다."})


@router.post("/notify-settings")
def api_save_notify_settings(request: Request, body: dict = Body(default={})):
    """잡별 알림 채널 설정 저장. body: {job_id, channel, enabled}"""
    if not get_login_user(request):
        return login_required_response()
    job_id  = body.get('job_id', '').strip()
    channel = body.get('channel', '').strip()
    enabled = body.get('enabled', True)
    if not job_id or channel not in ('kakao', 'email'):
        return JSONResponse(
            {"ok": False, "error": "job_id와 channel(kakao/email)이 필요합니다."},
            status_code=400,
        )
    try:
        from agent.scheduler import set_notify_setting
        set_notify_setting(job_id, channel, bool(enabled))
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"[agent/notify-settings/save] {e}", exc_info=True)
        return JSONResponse({"ok": False, "error": "서버 오류가 발생했습니다."}, status_code=500)
