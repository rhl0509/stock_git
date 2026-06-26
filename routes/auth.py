import re
import time as _time
import logging
from collections import defaultdict

from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse, RedirectResponse
from werkzeug.security import generate_password_hash, check_password_hash as _werkzeug_check
from database.db_connection import get_db_connection
from templates_config import render
from config import Config

router = APIRouter()
logger = logging.getLogger(__name__)

# ── 브루트포스 방어: IP + user_id 별 실패 횟수 추적 ──
_login_attempts: dict = defaultdict(list)
_RATE_LIMIT    = 5     # 허용 횟수
_RATE_WINDOW   = 300   # 초 (5분)
_MAX_TRACKED   = 10000 # 추적 키 상한 — 무한 메모리 증가 방지


def _is_rate_limited(identifier: str, limit: int = _RATE_LIMIT) -> bool:
    now    = _time.time()
    cutoff = now - _RATE_WINDOW
    # 키 수가 상한 초과 시 만료된 키 일괄 정리 (메모리 캡)
    if len(_login_attempts) > _MAX_TRACKED:
        for k in [k for k, v in _login_attempts.items() if not v or v[-1] <= cutoff]:
            _login_attempts.pop(k, None)
    valid  = [t for t in _login_attempts[identifier] if t > cutoff]
    _login_attempts[identifier] = valid
    if len(valid) >= limit:
        return True
    _login_attempts[identifier].append(now)
    return False


def _reset_attempts(identifier: str):
    _login_attempts.pop(identifier, None)


def _normalize_phone(raw: str) -> str | None:
    """휴대폰 번호를 숫자만 남겨 정규화. 한국 휴대폰(01X-XXXX(X)-XXXX, 10~11자리)만 허용.
    유효하지 않으면 None. 결제(PG)·구매자 식별에 쓰이므로 형식을 강제한다."""
    digits = re.sub(r'\D', '', raw or '')
    if re.fullmatch(r'01[016789]\d{7,8}', digits):
        return digits
    return None


def _check_password(pwhash: str, password: str) -> bool:
    """werkzeug(scrypt/pbkdf2) + bcrypt($2a/$2b) 두 형식 모두 지원."""
    if not pwhash:
        return False
    if pwhash.startswith(('$2a$', '$2b$', '$2y$')):
        import bcrypt
        try:
            return bcrypt.checkpw(password.encode('utf-8'), pwhash.encode('utf-8'))
        except Exception:
            return False
    try:
        return _werkzeug_check(pwhash, password)
    except Exception:
        return False


@router.post('/register')
def register(request: Request, data: dict = Body(default={})):
    client_ip = request.client.host if request.client else 'unknown'
    if _is_rate_limited(f"register:{client_ip}"):
        return JSONResponse({"error": "요청 횟수 초과. 잠시 후 다시 시도하세요."}, status_code=429)

    user_id  = (data.get('user_id') or '').strip()
    password = data.get('password', '')
    name     = (data.get('name') or '').strip()
    email    = (data.get('email') or '').strip()
    phone    = (data.get('phone') or '').strip()

    if not all([user_id, password, name, email, phone]):
        return JSONResponse({"error": "모든 필드를 입력해주세요."}, status_code=400)
    if len(user_id) < 3 or len(user_id) > 30:
        return JSONResponse({"error": "아이디는 3~30자여야 합니다."}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "비밀번호는 8자 이상이어야 합니다."}, status_code=400)
    if '@' not in email:
        return JSONResponse({"error": "유효한 이메일 주소를 입력하세요."}, status_code=400)
    phone = _normalize_phone(phone)
    if not phone:
        return JSONResponse({"error": "유효한 휴대폰 번호를 입력하세요."}, status_code=400)

    hashed_password = generate_password_hash(password)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM members WHERE user_id = %s", (user_id,))
            if cursor.fetchone():
                return JSONResponse({"error": "이미 존재하는 아이디입니다."}, status_code=409)
            cursor.execute(
                "INSERT INTO members (user_id, password_hash, name, email, phone, role, status) VALUES (%s, %s, %s, %s, %s, 'free', 'active')",
                (user_id, hashed_password, name, email, phone)
            )
        conn.commit()
        return JSONResponse({"message": "회원가입이 완료되었습니다! 로그인해주세요."}, status_code=201)
    except Exception as e:
        conn.rollback()
        logger.error(f"[auth/register] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


@router.get('/login')
def login_get(request: Request):
    if 'user_no' in request.session:
        return RedirectResponse(url='/', status_code=302)
    return render(request, 'auth/login.html')


@router.post('/login')
def login(request: Request, data: dict = Body(default={})):
    if not data:
        return JSONResponse({"error": "데이터가 전송되지 않았습니다."}, status_code=400)

    user_id  = (data.get('user_id') or '').strip()
    password = data.get('password', '')

    if not user_id or not password:
        return JSONResponse({"error": "아이디와 비밀번호를 입력해주세요."}, status_code=400)

    # IP + user_id 조합으로 레이트 리밋
    client_ip = request.client.host if request.client else 'unknown'
    rate_key  = f"{client_ip}:{user_id}"
    if _is_rate_limited(rate_key):
        return JSONResponse(
            {"error": f"로그인 시도 횟수 초과. {_RATE_WINDOW // 60}분 후 다시 시도하세요."},
            status_code=429
        )

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, password_hash, name, role FROM members WHERE user_id = %s AND status = 'active'",
                (user_id,)
            )
            user = cursor.fetchone()
            if user and _check_password(user['password_hash'], password):
                _reset_attempts(rate_key)
                request.session['user_no']   = user['id']
                request.session['user_id']   = user['user_id']
                request.session['user_name'] = user['name']
                request.session['role']      = user.get('role') or 'free'
                return JSONResponse({"message": "로그인 성공"}, status_code=200)
            else:
                return JSONResponse({"error": "아이디 또는 비밀번호가 틀립니다."}, status_code=401)
    except Exception as e:
        logger.error(f"[auth/login] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


@router.get('/logout')
def logout_get(request: Request):
    request.session.clear()
    return RedirectResponse(url='/login', status_code=302)


@router.post('/logout')
def logout_post(request: Request):
    request.session.clear()
    return JSONResponse({"message": "로그아웃 완료"})


@router.get('/me')
@router.get('/api/me')
def api_me(request: Request):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, name, email, role FROM members WHERE id=%s",
                (request.session['user_no'],)
            )
            row = cursor.fetchone()
        if not row:
            return JSONResponse({"error": "사용자 없음"}, status_code=404)
        role = row.get('role') or 'free'
        from routes.utils import is_owner
        from routes.tier import AI_FEATURE_MIN_TIER, has_tier
        # 프론트가 등급/AI잠금 상태로 버튼 노출을 제어할 수 있게 내려준다.
        ai_access = {feat: has_tier(request, AI_FEATURE_MIN_TIER[feat])
                     for feat in AI_FEATURE_MIN_TIER}
        return JSONResponse({
            "id":       row['id'],
            "user_id":  row['user_id'],
            "name":     row['name'],
            "user_name": row['name'],   # Sidebar 호환
            "email":    row.get('email', ''),
            "role":     'admin' if is_owner(request) else role,
            "is_owner": is_owner(request),
            "ai_access": ai_access,
        })
    finally:
        conn.close()


@router.post('/update-profile')
def update_profile(request: Request, data: dict = Body(default={})):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    name   = data.get('name', '').strip()
    email  = data.get('email', '').strip()
    phone  = (data.get('phone') or '').strip()
    new_pw = data.get('new_password', '').strip()
    cur_pw = data.get('current_password', '').strip()

    if not name:
        return JSONResponse({"error": "이름을 입력해주세요."}, status_code=400)
    # 가입 시 필수 필드인 이메일을 빈 값으로 덮어쓰지 못하게 막음
    if not email or '@' not in email:
        return JSONResponse({"error": "유효한 이메일 주소를 입력하세요."}, status_code=400)
    phone = _normalize_phone(phone)
    if not phone:
        return JSONResponse({"error": "유효한 휴대폰 번호를 입력하세요."}, status_code=400)
    if new_pw and len(new_pw) < 8:
        return JSONResponse({"error": "새 비밀번호는 8자 이상이어야 합니다."}, status_code=400)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM members WHERE id=%s", (request.session['user_no'],))
            row = cursor.fetchone()
            if not row:
                return JSONResponse({"error": "사용자 없음"}, status_code=404)

            if new_pw:
                if not cur_pw or not _check_password(row['password_hash'], cur_pw):
                    return JSONResponse({"error": "현재 비밀번호가 틀립니다."}, status_code=400)
                hashed = generate_password_hash(new_pw)
                cursor.execute(
                    "UPDATE members SET name=%s, email=%s, phone=%s, password_hash=%s WHERE id=%s",
                    (name, email, phone, hashed, request.session['user_no'])
                )
            else:
                cursor.execute(
                    "UPDATE members SET name=%s, email=%s, phone=%s WHERE id=%s",
                    (name, email, phone, request.session['user_no'])
                )
        conn.commit()
        request.session['user_name'] = name
        return JSONResponse({"message": "프로필이 업데이트되었습니다."})
    except Exception as e:
        conn.rollback()
        logger.error(f"[auth/update-profile] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


# ── React MyPage 계약 (GET/PUT /auth/profile, PUT /auth/change-password) ──

@router.get('/profile')
def get_profile(request: Request):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, name, email, phone, DATE_FORMAT(created_at,'%%Y-%%m-%%d') AS created_at "
                "FROM members WHERE id=%s", (request.session['user_no'],))
            row = cursor.fetchone()
        if not row:
            return JSONResponse({"error": "사용자 없음"}, status_code=404)
        return JSONResponse(row)
    finally:
        conn.close()


@router.put('/profile')
def put_profile(request: Request, data: dict = Body(default={})):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    name  = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()
    if not name:
        return JSONResponse({"error": "이름을 입력해주세요."}, status_code=400)
    if not email or '@' not in email:
        return JSONResponse({"error": "유효한 이메일 주소를 입력하세요."}, status_code=400)
    phone = _normalize_phone(phone)
    if not phone:
        return JSONResponse({"error": "유효한 휴대폰 번호를 입력하세요."}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE members SET name=%s, email=%s, phone=%s WHERE id=%s",
                           (name, email, phone, request.session['user_no']))
        conn.commit()
        request.session['user_name'] = name
        return JSONResponse({"message": "정보가 수정되었습니다."})
    except Exception as e:
        conn.rollback()
        logger.error(f"[auth/profile] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


@router.put('/change-password')
def change_password(request: Request, data: dict = Body(default={})):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    cur_pw = data.get('current_password', '')
    new_pw = data.get('new_password', '')
    if not cur_pw or not new_pw:
        return JSONResponse({"error": "현재/새 비밀번호를 모두 입력하세요."}, status_code=400)
    if len(new_pw) < 8:
        return JSONResponse({"error": "새 비밀번호는 8자 이상이어야 합니다."}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM members WHERE id=%s", (request.session['user_no'],))
            row = cursor.fetchone()
            if not row or not _check_password(row['password_hash'], cur_pw):
                return JSONResponse({"error": "현재 비밀번호가 틀립니다."}, status_code=400)
            cursor.execute("UPDATE members SET password_hash=%s WHERE id=%s",
                           (generate_password_hash(new_pw), request.session['user_no']))
        conn.commit()
        return JSONResponse({"message": "비밀번호가 변경되었습니다."})
    except Exception as e:
        conn.rollback()
        logger.error(f"[auth/change-password] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


# ── 아이디/비밀번호 찾기 (React FindAccount 계약) ──

def _mask_user_id(uid: str) -> str:
    """user_id를 앞 2자 + 마스킹 + 마지막 1자로 가린다 (find-account와 동일 규칙)."""
    if len(uid) > 3:
        return uid[:2] + '*' * (len(uid) - 3) + uid[-1]
    return uid[0] + '*' * (len(uid) - 1)


@router.post('/find-id')
def find_id(request: Request, data: dict = Body(default={})):
    """이름+이메일이 모두 일치하면 '마스킹된' 아이디 힌트만 반환 (평문 미반환, 레이트리밋 적용).

    평문 user_id를 그대로 주면 계정 열거 + 비밀번호 재설정의 첫 단계가 되므로
    힌트만 제공하고, 정확한 아이디는 등록 이메일로 안내한다.
    """
    client_ip = request.client.host if request.client else 'unknown'
    if _is_rate_limited(f"findid:{client_ip}"):
        return JSONResponse({"error": "요청 횟수 초과. 잠시 후 다시 시도하세요."}, status_code=429)
    name  = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    if not name or not email or '@' not in email:
        return JSONResponse({"error": "이름과 이메일을 입력해주세요."}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, DATE_FORMAT(created_at,'%%Y-%%m-%%d') AS created_at "
                "FROM members WHERE name=%s AND email=%s AND status='active'",
                (name, email))
            row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return JSONResponse({"error": "일치하는 계정이 없습니다."}, status_code=404)
    return JSONResponse({
        "hint":       _mask_user_id(row['user_id']),
        "created_at": row['created_at'],
        "message":    "아이디 일부만 표시됩니다. 전체 아이디는 가입 이메일로 확인하세요.",
    })


# ── 비밀번호 재설정: 토큰 발급 메일 → 토큰으로 새 비밀번호 설정 ──

_RESET_TOKEN_TTL_MIN = 30   # 재설정 링크 유효시간(분)
_reset_table_ready = False


def _ensure_reset_table(conn) -> None:
    """password_reset_tokens 테이블 보장 (프로세스당 1회)."""
    global _reset_table_ready
    if _reset_table_ready:
        return
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                member_id   INT          NOT NULL,
                token_hash  CHAR(64)     NOT NULL,
                expires_at  DATETIME     NOT NULL,
                used        TINYINT(1)   NOT NULL DEFAULT 0,
                created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_token_hash (token_hash),
                INDEX idx_member (member_id)
            )
        """)
    conn.commit()
    _reset_table_ready = True


@router.post('/find-password')
def find_password(request: Request, data: dict = Body(default={})):
    """아이디+이메일 일치 시 '재설정 링크'를 등록 이메일로 발송 (레이트리밋 적용).

    임시 비밀번호를 응답으로 반환하지 않으며, 메일 수신(본인 확인) 없이는
    비밀번호가 바뀌지 않는다. 계정 열거 방지를 위해 존재 여부와 무관하게
    동일한 성공 응답을 반환한다.
    """
    import hashlib
    import secrets as _secrets
    from datetime import datetime, timedelta
    from notify.email_send import send_password_reset

    client_ip = request.client.host if request.client else 'unknown'
    if _is_rate_limited(f"findpw:{client_ip}"):
        return JSONResponse({"error": "요청 횟수 초과. 잠시 후 다시 시도하세요."}, status_code=429)
    user_id = (data.get('user_id') or '').strip()
    email   = (data.get('email') or '').strip()
    if not user_id or not email:
        return JSONResponse({"error": "아이디와 이메일을 입력해주세요."}, status_code=400)

    # 존재 여부와 무관하게 동일하게 응답할 메시지 (계정 열거 방지)
    generic_ok = JSONResponse({
        "message": "입력하신 정보와 일치하는 계정이 있다면 재설정 링크를 이메일로 보냈습니다. "
                   "메일함을 확인해주세요."
    })

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, email FROM members WHERE user_id=%s AND email=%s AND status='active'",
                (user_id, email))
            row = cursor.fetchone()

        if not row:
            return generic_ok   # 열거 방지: 실패도 성공처럼 응답

        _ensure_reset_table(conn)
        raw_token  = _secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now() + timedelta(minutes=_RESET_TOKEN_TTL_MIN)
        with conn.cursor() as cursor:
            # 해당 계정의 기존 미사용 토큰 무효화 후 새 토큰 발급
            cursor.execute(
                "UPDATE password_reset_tokens SET used=1 WHERE member_id=%s AND used=0",
                (row['id'],))
            cursor.execute(
                "INSERT INTO password_reset_tokens (member_id, token_hash, expires_at) "
                "VALUES (%s, %s, %s)",
                (row['id'], token_hash, expires_at))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[auth/find-password] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()

    reset_url = f"{Config.APP_BASE_URL}/reset-password?token={raw_token}"
    sent = send_password_reset(row['email'], reset_url, _RESET_TOKEN_TTL_MIN)
    if not sent:
        # 메일 발송 실패는 서버 로그로만 남기고, 응답은 동일하게 유지(열거/설정상태 노출 방지)
        logger.error("[auth/find-password] 재설정 메일 발송 실패 (SMTP 설정 확인 필요)")
    return generic_ok


@router.post('/reset-password')
def reset_password(request: Request, data: dict = Body(default={})):
    """재설정 토큰 + 새 비밀번호로 실제 비밀번호 변경."""
    import hashlib
    from datetime import datetime

    client_ip = request.client.host if request.client else 'unknown'
    if _is_rate_limited(f"resetpw:{client_ip}"):
        return JSONResponse({"error": "요청 횟수 초과. 잠시 후 다시 시도하세요."}, status_code=429)

    token    = (data.get('token') or '').strip()
    password = data.get('password', '')
    if not token or not password:
        return JSONResponse({"error": "토큰과 새 비밀번호가 필요합니다."}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "비밀번호는 8자 이상이어야 합니다."}, status_code=400)

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db_connection()
    try:
        _ensure_reset_table(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, member_id, expires_at, used FROM password_reset_tokens "
                "WHERE token_hash=%s",
                (token_hash,))
            tok = cursor.fetchone()
            if not tok or tok['used'] or tok['expires_at'] < datetime.now():
                return JSONResponse(
                    {"error": "유효하지 않거나 만료된 링크입니다. 다시 요청해주세요."},
                    status_code=400)
            cursor.execute("UPDATE members SET password_hash=%s WHERE id=%s",
                           (generate_password_hash(password), tok['member_id']))
            cursor.execute("UPDATE password_reset_tokens SET used=1 WHERE id=%s", (tok['id'],))
        conn.commit()
        return JSONResponse({"message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인하세요."})
    except Exception as e:
        conn.rollback()
        logger.error(f"[auth/reset-password] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()


@router.post('/find-account')
def find_account_post(request: Request, data: dict = Body(default={})):
    """이메일로 계정 존재 여부 확인 — user_id는 절대 평문 반환하지 않음."""
    client_ip = request.client.host if request.client else 'unknown'
    if _is_rate_limited(f"find:{client_ip}"):
        return JSONResponse({"error": "요청 횟수 초과. 잠시 후 다시 시도하세요."}, status_code=429)

    email = data.get('email', '').strip()
    if not email or '@' not in email:
        return JSONResponse({"error": "유효한 이메일을 입력해주세요."}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id FROM members WHERE email=%s", (email,))
            row = cursor.fetchone()
        if row:
            uid    = row['user_id']
            # 앞 2자 + 마스킹 + 마지막 1자 힌트만 제공
            if len(uid) > 3:
                masked = uid[:2] + '*' * (len(uid) - 3) + uid[-1]
            else:
                masked = uid[0] + '*' * (len(uid) - 1)
            return JSONResponse({"found": True, "hint": masked})
        return JSONResponse({"error": "해당 이메일로 가입된 계정이 없습니다."}, status_code=404)
    except Exception as e:
        logger.error(f"[auth/find-account] {e}", exc_info=True)
        return JSONResponse({"error": "서버 오류가 발생했습니다."}, status_code=500)
    finally:
        conn.close()
