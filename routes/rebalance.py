"""routes/rebalance.py — 리밸런싱 목표 비중 + 이메일 설정 API."""
import logging
from decimal import Decimal
from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse
from routes.utils import get_login_user, login_required_response
from database.db_connection import get_db_connection

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rebalance_targets (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    user_no     INT NOT NULL,
                    stock_code  VARCHAR(20) NOT NULL,
                    target_pct  DECIMAL(5,2) NOT NULL,
                    threshold   DECIMAL(5,2) DEFAULT 5.0,
                    created_at  DATETIME DEFAULT NOW(),
                    UNIQUE KEY uk_user_code (user_no, stock_code)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()

try:
    _ensure_table()
except Exception:
    pass


# ── 리밸런싱 목표 ─────────────────────────────────────────────────

@router.get('/api/rebalance/targets')
def get_targets(request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, stock_code, target_pct, threshold FROM rebalance_targets "
                "WHERE user_no=%s ORDER BY id",
                (user['user_no'],)
            )
            rows = cur.fetchall()
        # DECIMAL(target_pct/threshold) → float (json.dumps 직렬화 불가 방지)
        for r in rows:
            for k, v in r.items():
                if isinstance(v, Decimal):
                    r[k] = float(v)
        return JSONResponse({'ok': True, 'targets': rows})
    except Exception as e:
        logger.error(f'[rebalance/get] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post('/api/rebalance/targets')
def upsert_target(request: Request, body: dict = Body(default={})):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    if not body.get('stock_code') or body.get('target_pct') is None:
        return JSONResponse({'ok': False, 'error': '종목코드와 목표비중은 필수입니다.'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rebalance_targets (user_no, stock_code, target_pct, threshold)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE target_pct=VALUES(target_pct), threshold=VALUES(threshold)
            """, (user['user_no'], body['stock_code'], body['target_pct'], body.get('threshold', 5.0)))
            conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f'[rebalance/upsert] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.delete('/api/rebalance/targets/{stock_code}')
def delete_target(stock_code: str, request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rebalance_targets WHERE user_no=%s AND stock_code=%s",
                (user['user_no'], stock_code)
            )
            conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f'[rebalance/delete] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


# ── 이메일 설정 ──────────────────────────────────────────────────

@router.get('/api/settings/email')
def get_email_config(request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT `key`, `value` FROM app_settings WHERE `key` LIKE 'email_%'")
            rows = cur.fetchall()
        cfg = {r['key']: r['value'] for r in rows}
        if cfg.get('email_password'):
            cfg['email_password'] = '••••••••'
        return JSONResponse({'ok': True, 'config': cfg})
    except Exception as e:
        logger.error(f'[settings/email/get] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post('/api/settings/email')
def save_email_config(request: Request, body: dict = Body(default={})):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    allowed = ['email_enabled', 'email_to', 'email_user', 'email_password',
               'email_smtp_host', 'email_smtp_port']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for key in allowed:
                val = body.get(key)
                if val is None:
                    continue
                # 마스킹된 값은 저장하지 않음
                if key == 'email_password' and val == '••••••••':
                    continue
                # 비밀번호는 암호화해서 저장
                if key == 'email_password' and val:
                    from notify.email_send import encrypt_password
                    val = encrypt_password(val)
                cur.execute("""
                    INSERT INTO app_settings (`key`, `value`) VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)
                """, (key, str(val)))
            conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f'[settings/email/save] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post('/api/settings/email/test')
def test_email(request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    try:
        from notify.email_send import send_email
        ok = send_email('[GAGYE] 이메일 알림 테스트', '이메일 알림이 정상적으로 설정되었습니다.')
        return JSONResponse({'ok': ok, 'message': '발송 성공' if ok else '발송 실패 (설정 확인 필요)'})
    except Exception as e:
        logger.error(f'[settings/email/test] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'message': '서버 오류가 발생했습니다.'}, status_code=500)
