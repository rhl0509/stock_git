"""
routes/notify_history.py — 알림 발송 히스토리 API + 페이지.
"""
from fastapi import APIRouter, Request, Depends
from database.db_connection import get_db_connection
from routes.utils import require_login, api_require_login
from templates_config import render

router = APIRouter()


@router.get("/notify_history", dependencies=[Depends(require_login)])
def notify_history_page(request: Request):
    return render(request, "stock/notify_history.html")


@router.get("/api/notify/history", dependencies=[Depends(api_require_login)])
def get_notify_history(request: Request):
    limit  = min(int(request.query_params.get("limit", 50)), 200)
    offset = int(request.query_params.get("offset", 0))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, channel, message, ok, error_msg,
                       DATE_FORMAT(sent_at, '%%Y-%%m-%%d %%H:%%i:%%s') AS sent_at
                FROM notify_history
                ORDER BY sent_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS cnt FROM notify_history")
            total = cur.fetchone()["cnt"]
    finally:
        conn.close()

    return {"ok": True, "total": total, "rows": rows}


@router.get("/api/notify/history/stats", dependencies=[Depends(api_require_login)])
def get_notify_stats():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*)                              AS total,
                    SUM(ok = 1)                           AS success,
                    SUM(ok = 0)                           AS failure,
                    DATE_FORMAT(MAX(sent_at), '%%Y-%%m-%%d %%H:%%i') AS last_sent
                FROM notify_history
            """)
            stats = cur.fetchone()
    finally:
        conn.close()

    return {"ok": True, "stats": stats}
