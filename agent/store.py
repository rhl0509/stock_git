"""
agent/store.py
==============
market_reports 테이블 CRUD.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def save_report(
    report_type: str,
    report_date: str,
    title: str,
    content: str,
    summary: str = "",
) -> int:
    """보고서 저장. 같은 (type, date)면 내용 덮어씀. 저장된 id 반환."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_reports (report_type, report_date, title, content, summary)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title   = VALUES(title),
                    content = VALUES(content),
                    summary = VALUES(summary),
                    created_at = NOW()
                """,
                (report_type, report_date, title, content, summary),
            )
            # LAST_INSERT_ID()는 UPDATE 시 0을 반환하므로 직접 조회
            cur.execute(
                "SELECT id FROM market_reports WHERE report_type=%s AND report_date=%s",
                (report_type, report_date),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"] if row else 0
    except Exception as e:
        logger.error(f"[store] save_report 실패: {e}")
        raise
    finally:
        conn.close()


def get_report_by_date(report_type: str, report_date: str) -> Optional[dict]:
    """특정 타입/날짜 보고서 조회."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM market_reports WHERE report_type=%s AND report_date=%s",
                (report_type, report_date),
            )
            return cur.fetchone()
    except Exception as e:
        logger.error(f"[store] get_report_by_date 실패: {e}")
        return None
    finally:
        conn.close()


def get_reports(report_type: str | None = None, limit: int = 20, offset: int = 0) -> list[dict]:
    """보고서 목록 조회 (최신순)."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if report_type:
                cur.execute(
                    "SELECT id, report_type, report_date, title, summary, created_at "
                    "FROM market_reports WHERE report_type=%s "
                    "ORDER BY report_date DESC LIMIT %s OFFSET %s",
                    (report_type, limit, offset),
                )
            else:
                cur.execute(
                    "SELECT id, report_type, report_date, title, summary, created_at "
                    "FROM market_reports "
                    "ORDER BY report_date DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            return cur.fetchall() or []
    except Exception as e:
        logger.error(f"[store] get_reports 실패: {e}")
        return []
    finally:
        conn.close()


def get_report_by_id(report_id: int) -> Optional[dict]:
    """ID로 보고서 전체 내용 조회."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM market_reports WHERE id=%s", (report_id,))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"[store] get_report_by_id 실패: {e}")
        return None
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# dart_summaries CRUD
# ─────────────────────────────────────────────────────────────────

def is_dart_summarized(rcept_no: str) -> bool:
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM dart_summaries WHERE rcept_no=%s", (rcept_no,))
            return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


def save_dart_summary(rcept_no: str, corp_name: str, report_nm: str, signal: str, summary: str):
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT IGNORE INTO dart_summaries
                    (rcept_no, corp_name, report_nm, `signal`, summary)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (rcept_no, corp_name, report_nm, signal, summary),
            )
        conn.commit()
    except Exception as e:
        logger.warning(f"[store] save_dart_summary 실패: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# event_calendar CRUD
# ─────────────────────────────────────────────────────────────────

def upsert_event(
    event_date: str,
    event_type: str,
    title: str,
    description: str = "",
    importance: str = "medium",
    country: str = "US",
) -> int:
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_calendar
                    (event_date, event_type, title, description, importance, country)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    title=VALUES(title), description=VALUES(description),
                    importance=VALUES(importance)
                """,
                (event_date, event_type, title, description, importance, country),
            )
            cur.execute(
                "SELECT id FROM event_calendar WHERE event_date=%s AND event_type=%s",
                (event_date, event_type),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"] if row else 0
    except Exception as e:
        logger.error(f"[store] upsert_event 실패: {e}")
        return 0
    finally:
        conn.close()


def get_events_for_date(target_date: str) -> list[dict]:
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM event_calendar WHERE event_date=%s ORDER BY importance DESC",
                (target_date,),
            )
            return cur.fetchall() or []
    except Exception as e:
        logger.warning(f"[store] get_events_for_date 실패: {e}")
        return []
    finally:
        conn.close()


def mark_event_notified(event_id: int):
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE event_calendar SET notified=1 WHERE id=%s", (event_id,))
        conn.commit()
    finally:
        conn.close()
