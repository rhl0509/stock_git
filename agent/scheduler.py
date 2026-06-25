"""
agent/scheduler.py
==================
보고서 에이전트 스케줄러. app.py 기동 시 start()를 호출해 백그라운드 실행.

스케줄:
  보고서
    - 일간:           평일 20:30
    - 주간:           금요일 20:30
    - 월간:           매월 마지막 날 20:30
  에이전트
    - 추천 성과 추적: 평일 09:30
    - 이상 감지:      평일 10:00, 13:00, 15:00
    - 경제 이벤트:    매일 18:00
    - 공시 요약:      평일 장중 매 60분 (10~15시)
    - 수급 모니터링:  평일 15:40
    - 장전갭리스크:   평일 08:35 (간밤 美증시·선물·VIX, 위험 시 손절 무장)
    - 코스피변동감지: 평일 장중 매 분 (09~15시, 단계×시간창×방향+속도 선행경보)
    - 실적 모니터링:  평일 17:00
    - 리밸런싱 알림:  평일 16:00

수동 실행:
  python -m agent.scheduler --run daily
  python -m agent.scheduler --run weekly
  python -m agent.scheduler --run monthly
  python -m agent.scheduler --run performance
  python -m agent.scheduler --run anomaly
  python -m agent.scheduler --run events
  python -m agent.scheduler --run dart
  python -m agent.scheduler --run flow
  python -m agent.scheduler --run earnings
  python -m agent.scheduler --run rebalance
"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────
# DB 테이블 초기화
# ─────────────────────────────────────────────────────────────────

def _ensure_tables():
    """에이전트 관련 테이블 생성 (없을 때만)."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_run_log (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    job_id       VARCHAR(50) NOT NULL,
                    triggered_by ENUM('scheduler','manual') DEFAULT 'scheduler',
                    started_at   DATETIME NOT NULL,
                    finished_at  DATETIME,
                    status       ENUM('running','success','failed') DEFAULT 'running',
                    summary      TEXT,
                    error_msg    TEXT,
                    INDEX idx_job_time (job_id, started_at DESC),
                    INDEX idx_started  (started_at DESC)
                ) CHARACTER SET utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_notify_settings (
                    id      INT AUTO_INCREMENT PRIMARY KEY,
                    job_id  VARCHAR(50) NOT NULL,
                    channel ENUM('email','kakao') NOT NULL,
                    enabled TINYINT(1) DEFAULT 1,
                    UNIQUE KEY uk_job_channel (job_id, channel)
                ) CHARACTER SET utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dart_summaries (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    rcept_no   VARCHAR(30) NOT NULL,
                    corp_name  VARCHAR(100),
                    report_nm  VARCHAR(255),
                    `signal`   VARCHAR(20) DEFAULT NULL,
                    summary    VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_rcept (rcept_no),
                    INDEX idx_created (created_at DESC)
                ) CHARACTER SET utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_anomaly_results (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    detected_at DATETIME NOT NULL,
                    ticker      VARCHAR(20),
                    name        VARCHAR(100),
                    price       DECIMAL(12,2),
                    price_chg   DECIMAL(6,2),
                    vol_ratio   DECIMAL(6,2),
                    signals     VARCHAR(255),
                    explanation TEXT,
                    INDEX idx_detected (detected_at DESC)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    except Exception as e:
        logger.warning(f"[scheduler] 테이블 초기화 실패: {e}")
    finally:
        conn.close()


try:
    _ensure_tables()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────────
# 이력 로그 · 알림 설정 헬퍼
# ─────────────────────────────────────────────────────────────────

def run_and_log(job_id: str, fn, triggered_by: str = 'scheduler') -> dict:
    """잡 실행 + DB 이력 기록. agent_dashboard에서도 호출됨."""
    from database.db_connection import get_db_connection

    start  = datetime.now()
    run_id = None

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_run_log (job_id, triggered_by, started_at, status) VALUES (%s,%s,%s,'running')",
                (job_id, triggered_by, start),
            )
            conn.commit()
            run_id = cur.lastrowid
    except Exception:
        pass
    finally:
        conn.close()

    try:
        result = fn()
        status  = 'success'
        summary = str(result)[:500] if result else '완료'
        error   = None
    except Exception as exc:
        status  = 'failed'
        summary = None
        error   = str(exc)[:1000]
        logger.error(f"[scheduler] {job_id} 실패: {exc}", exc_info=True)
        result  = {}

    if run_id:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_run_log SET finished_at=%s, status=%s, summary=%s, error_msg=%s WHERE id=%s",
                    (datetime.now(), status, summary, error, run_id),
                )
                conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    return {'ok': status == 'success', 'job_id': job_id, 'status': status, 'run_id': run_id}


def _should_notify(job_id: str, channel: str) -> bool:
    """DB에서 알림 채널 활성화 여부 조회. 설정 없으면 기본값 True."""
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT enabled FROM agent_notify_settings WHERE job_id=%s AND channel=%s",
                (job_id, channel),
            )
            row = cur.fetchone()
        conn.close()
        if row is not None:
            return bool(row['enabled'])
    except Exception:
        pass
    return True


def get_run_log(job_id: str | None = None, limit: int = 30) -> list[dict]:
    """실행 이력 반환 (API 응답용)."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if job_id:
                cur.execute(
                    "SELECT * FROM agent_run_log WHERE job_id=%s ORDER BY started_at DESC LIMIT %s",
                    (job_id, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM agent_run_log ORDER BY started_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall() or []
        return [{k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in r.items()} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_notify_settings() -> list[dict]:
    """전체 알림 설정 반환."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT job_id, channel, enabled FROM agent_notify_settings")
            rows = cur.fetchall() or []
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def set_notify_setting(job_id: str, channel: str, enabled: bool):
    """알림 설정 upsert."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_notify_settings (job_id, channel, enabled)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE enabled = VALUES(enabled)""",
                (job_id, channel, 1 if enabled else 0),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[scheduler] notify_setting 저장 실패: {e}", exc_info=True)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# 보고서 잡
# ─────────────────────────────────────────────────────────────────

def _job_daily():
    def fn():
        from agent.report_daily import run
        return run(send_kakao=_should_notify('report_daily', 'kakao'))
    run_and_log('report_daily', fn)


def _job_weekly():
    def fn():
        from agent.report_weekly import run
        return run(send_kakao=_should_notify('report_weekly', 'kakao'))
    run_and_log('report_weekly', fn)


def _job_monthly():
    def fn():
        from agent.report_monthly import run
        return run(send_kakao=_should_notify('report_monthly', 'kakao'))
    run_and_log('report_monthly', fn)


# ─────────────────────────────────────────────────────────────────
# 에이전트 잡
# ─────────────────────────────────────────────────────────────────

def _job_performance():
    def fn():
        from agent.report_performance import run
        return run(send_kakao=_should_notify('agent_performance', 'kakao'))
    run_and_log('agent_performance', fn)


def _job_anomaly():
    def fn():
        from agent.anomaly_detector import run
        return run(send_kakao=_should_notify('agent_anomaly', 'kakao'))
    run_and_log('agent_anomaly', fn)


def _job_events():
    def fn():
        from agent.event_calendar import run
        return run(send_kakao=_should_notify('agent_events', 'kakao'))
    run_and_log('agent_events', fn)


def _job_dart():
    def fn():
        from agent.dart_summarizer import run
        return run(send_kakao=_should_notify('agent_dart', 'kakao'))
    run_and_log('agent_dart', fn)


def _job_flow():
    def fn():
        from agent.flow_monitor import run
        return run(send_kakao=_should_notify('agent_flow', 'kakao'))
    run_and_log('agent_flow', fn)


def _job_earnings():
    def fn():
        from agent.earnings_monitor import run
        return run(send_kakao=_should_notify('agent_earnings', 'kakao'))
    run_and_log('agent_earnings', fn)


def _job_rebalance():
    def fn():
        from agent.rebalance_alert import run
        return run(send_kakao=_should_notify('agent_rebalance', 'kakao'))
    run_and_log('agent_rebalance', fn)


def _job_watchdog():
    def fn():
        from agent.holdings_watchdog import run
        return run(send_kakao=_should_notify('agent_watchdog', 'kakao'))
    run_and_log('agent_watchdog', fn)


def _job_drift():
    def fn():
        from agent.model_drift import run
        return run(send_kakao=_should_notify('agent_drift', 'kakao'))
    run_and_log('agent_drift', fn)


def _job_autostop():
    def fn():
        from agent.auto_stop_alert import run
        return run(send_kakao=_should_notify('agent_autostop', 'kakao'))
    run_and_log('agent_autostop', fn)


def _job_sidecar():
    # 매 분 호출 — 지수 트리거가 없으면 가벼운 지수 조회만 하고 즉시 반환한다.
    # agent_run_log 폭주를 막기 위해 실제 사이드카 스캔이 '발동'했을 때만 이력 기록.
    from agent.sidecar_monitor import check_and_scan
    res = check_and_scan(send_kakao=_should_notify('agent_sidecar', 'kakao'))
    if res.get('triggered'):
        run_and_log('agent_sidecar', lambda: res)


def _job_gap_risk():
    def fn():
        from agent.gap_risk import run
        return run(send_kakao=_should_notify('agent_gap_risk', 'kakao'))
    run_and_log('agent_gap_risk', fn)


# ─────────────────────────────────────────────────────────────────
# 스케줄러 시작/종료
# ─────────────────────────────────────────────────────────────────

def start(scheduler: BackgroundScheduler | None = None):
    """
    보고서 잡을 스케줄러에 등록.
    scheduler를 전달하면 기존 인스턴스에 잡만 추가 (인스턴스 중복 방지).
    """
    global _scheduler
    if scheduler is not None:
        _scheduler = scheduler
    elif _scheduler and _scheduler.running:
        logger.warning("[scheduler] 이미 실행 중")
        return
    else:
        _scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    tz = "Asia/Seoul"

    # ── 보고서 ──
    _scheduler.add_job(_job_daily,   CronTrigger(day_of_week="mon-fri", hour=20, minute=30, timezone=tz),
                       id="report_daily",   replace_existing=True, misfire_grace_time=3600)
    _scheduler.add_job(_job_weekly,  CronTrigger(day_of_week="fri",     hour=20, minute=30, timezone=tz),
                       id="report_weekly",  replace_existing=True, misfire_grace_time=3600)
    _scheduler.add_job(_job_monthly, CronTrigger(day="last",            hour=20, minute=30, timezone=tz),
                       id="report_monthly", replace_existing=True, misfire_grace_time=3600)

    # ── 에이전트 ──
    _scheduler.add_job(_job_performance, CronTrigger(day_of_week="mon-fri", hour=9,  minute=30, timezone=tz),
                       id="agent_performance", replace_existing=True, misfire_grace_time=1800)

    _scheduler.add_job(_job_anomaly, CronTrigger(day_of_week="mon-fri", hour="10,13,15", minute=0, timezone=tz),
                       id="agent_anomaly", replace_existing=True, misfire_grace_time=1800)

    _scheduler.add_job(_job_events,  CronTrigger(hour=18, minute=0, timezone=tz),
                       id="agent_events",  replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_job_dart,    CronTrigger(day_of_week="mon-fri", hour="10-15", minute=0, timezone=tz),
                       id="agent_dart",    replace_existing=True, misfire_grace_time=1800)

    _scheduler.add_job(_job_flow,    CronTrigger(day_of_week="mon-fri", hour=15, minute=40, timezone=tz),
                       id="agent_flow",    replace_existing=True, misfire_grace_time=1800)

    _scheduler.add_job(_job_earnings, CronTrigger(day_of_week="mon-fri", hour=17, minute=0, timezone=tz),
                       id="agent_earnings", replace_existing=True, misfire_grace_time=1800)

    _scheduler.add_job(_job_rebalance, CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone=tz),
                       id="agent_rebalance", replace_existing=True, misfire_grace_time=1800)

    _scheduler.add_job(_job_watchdog, CronTrigger(day_of_week="mon-fri", hour="9-16", minute="5,35", timezone=tz),
                       id="agent_watchdog", replace_existing=True, misfire_grace_time=900)

    _scheduler.add_job(_job_drift, CronTrigger(day_of_week="mon", hour=9, minute=5, timezone=tz),
                       id="agent_drift", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_job_autostop, CronTrigger(day_of_week="mon-fri", hour=15, minute=55, timezone=tz),
                       id="agent_autostop", replace_existing=True, misfire_grace_time=1800)

    # 코스피 변동 세분화 감지(단계×시간창×방향) — 장중 매 분(09~15시). 에스컬레이션 시에만 스캔.
    _scheduler.add_job(_job_sidecar, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*", timezone=tz),
                       id="agent_sidecar", replace_existing=True, misfire_grace_time=50, max_instances=1, coalesce=True)

    # 장전 갭하락 위험 경보(간밤 美증시·지수선물·VIX) — 평일 08:35. 위험 시 손절 자동 무장.
    _scheduler.add_job(_job_gap_risk, CronTrigger(day_of_week="mon-fri", hour=8, minute=35, timezone=tz),
                       id="agent_gap_risk", replace_existing=True, misfire_grace_time=1800)

    if not _scheduler.running:
        _scheduler.start()
    logger.info("[scheduler] 에이전트 잡 등록 완료 (15개)")
    _log_next_runs()


def stop():
    """FastAPI shutdown 시 호출."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] 스케줄러 종료")


def _log_next_runs():
    if not _scheduler:
        return
    for job in _scheduler.get_jobs():
        logger.info(f"  [{job.id}] 다음 실행: {job.next_run_time}")


def get_status() -> list[dict]:
    """현재 스케줄 상태 반환 (API 응답용)."""
    if not _scheduler or not _scheduler.running:
        return []
    return [{"id": job.id, "next_run": str(job.next_run_time)} for job in _scheduler.get_jobs()]


# ─────────────────────────────────────────────────────────────────
# 수동 실행 (CLI)
# ─────────────────────────────────────────────────────────────────
_JOB_MAP = {
    "daily":       _job_daily,
    "weekly":      _job_weekly,
    "monthly":     _job_monthly,
    "performance": _job_performance,
    "anomaly":     _job_anomaly,
    "events":      _job_events,
    "dart":        _job_dart,
    "flow":        _job_flow,
    "earnings":    _job_earnings,
    "rebalance":   _job_rebalance,
    "watchdog":    _job_watchdog,
    "drift":       _job_drift,
    "autostop":    _job_autostop,
    "sidecar":     _job_sidecar,
    "gap_risk":    _job_gap_risk,
}

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    mode = "daily"
    if "--run" in sys.argv:
        idx = sys.argv.index("--run")
        if idx + 1 < len(sys.argv):
            mode = sys.argv[idx + 1]

    fn = _JOB_MAP.get(mode)
    if fn:
        print(f"[CLI] {mode} 수동 실행")
        fn()
    else:
        print(f"알 수 없는 모드: {mode}")
        print(f"선택 가능: {', '.join(_JOB_MAP)}")
        sys.exit(1)
