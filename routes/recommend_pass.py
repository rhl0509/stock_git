"""routes/recommend_pass.py — AI 추천 데이 패스(day pass).

하루(한국시간 07:00 ~ 다음날 07:00)에 1회 RECOMMEND_PASS_COST 크레딧을 차감하면
그날 AI 추천 열람이 활성화된다. 같은 날 껐다 켜도 재차감하지 않으며(OFF는 환불 없음),
07:00 이 지나면 새 패스가 필요하다(모델은 06:30 에 미리 생성됨).
"""
import logging
from datetime import datetime, timedelta, time

import pytz
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from config import Config

router = APIRouter()
logger = logging.getLogger(__name__)

KST = pytz.timezone('Asia/Seoul')


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recommend_pass (
                    user_no    INT        NOT NULL,
                    pass_day   DATE       NOT NULL,
                    enabled    TINYINT(1) NOT NULL DEFAULT 1,
                    charged    INT        NOT NULL DEFAULT 0,
                    created_at DATETIME   DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_no, pass_day)
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _pass_day(now=None):
    """현재 패스 기준일(date). 하루 경계는 KST RECOMMEND_PASS_RESET_HOUR(기본 07:00)."""
    now = now or datetime.now(KST)
    return (now - timedelta(hours=Config.RECOMMEND_PASS_RESET_HOUR)).date()


def _expires_at(pass_day):
    """pass_day 패스 만료 시각 = 다음날 RESET_HOUR(KST)."""
    exp = datetime.combine(pass_day + timedelta(days=1),
                           time(Config.RECOMMEND_PASS_RESET_HOUR, 0))
    return KST.localize(exp)


def has_active_pass(user_no) -> bool:
    """오늘 패스가 활성(결제됨 + enabled=1)인지."""
    if not user_no:
        return False
    pd = _pass_day()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT enabled FROM recommend_pass WHERE user_no=%s AND pass_day=%s",
                (user_no, pd))
            row = cur.fetchone()
        return bool(row and row['enabled'])
    finally:
        conn.close()


def _status_payload(user_no):
    from routes.credits import get_balance_value
    pd = _pass_day()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT enabled FROM recommend_pass WHERE user_no=%s AND pass_day=%s",
                (user_no, pd))
            row = cur.fetchone()
    finally:
        conn.close()
    active = bool(row and row['enabled'])
    return {
        "active":     active,
        "paid_today": bool(row),          # 오늘 이미 결제했는지(껐다 켜도 재차감 안 함)
        "pass_day":   pd.isoformat(),
        "cost":       Config.RECOMMEND_PASS_COST,
        "balance":    get_balance_value(user_no),
        "expires_at": _expires_at(pd).strftime('%Y-%m-%d %H:%M') if active else None,
    }


@router.get('/api/recommend-pass/status')
def pass_status(request: Request):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    return JSONResponse(_status_payload(request.session['user_no']))


@router.post('/api/recommend-pass/enable')
def pass_enable(request: Request):
    """AI 추천받기 ON. 오늘 첫 활성화면 크레딧 차감, 이미 결제일이면 재차감 없이 켜기만."""
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    user_no = request.session['user_no']
    pd = _pass_day()
    cost = Config.RECOMMEND_PASS_COST

    # 오늘 이미 결제했는지 확인 — 결제했으면 재차감 없이 enabled 만 복구
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT enabled FROM recommend_pass WHERE user_no=%s AND pass_day=%s",
                (user_no, pd))
            row = cur.fetchone()
        if row:
            if not row['enabled']:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE recommend_pass SET enabled=1 WHERE user_no=%s AND pass_day=%s",
                        (user_no, pd))
                conn.commit()
            return JSONResponse({**_status_payload(user_no), "charged": 0})
    finally:
        conn.close()

    # 신규 결제 — 크레딧 차감 후 패스 발급
    from routes.credits import deduct_credits
    d = deduct_credits(user_no, cost, memo=f"AI 추천 데이 패스 ({pd.isoformat()})")
    if not d.get('ok'):
        return JSONResponse(
            {"error": d.get('error') or "크레딧이 부족합니다.",
             "balance": d.get('balance'), "cost": cost},
            status_code=402)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO recommend_pass (user_no, pass_day, enabled, charged) "
                "VALUES (%s,%s,1,%s) ON DUPLICATE KEY UPDATE enabled=1",
                (user_no, pd, cost))
        conn.commit()
    finally:
        conn.close()

    return JSONResponse({**_status_payload(user_no), "charged": cost})


@router.post('/api/recommend-pass/disable')
def pass_disable(request: Request):
    """AI 추천받기 OFF. 당일 비활성화(환불 없음). 같은 날 다시 켜도 재차감 안 함."""
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    user_no = request.session['user_no']
    pd = _pass_day()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE recommend_pass SET enabled=0 WHERE user_no=%s AND pass_day=%s",
                (user_no, pd))
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({**_status_payload(user_no), "charged": 0})
