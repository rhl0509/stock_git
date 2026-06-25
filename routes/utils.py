# routes/utils.py — FastAPI 공통 유틸리티
from fastapi import Request
from fastapi.responses import JSONResponse


# ── 커스텀 예외 (의존성에서 raise → 앱 레벨 핸들러가 처리) ──

class LoginRequired(Exception):
    """HTML 페이지 라우트: 미인증 → /login 리다이렉트."""

class ApiLoginRequired(Exception):
    """JSON API 라우트: 미인증 → 401 JSON."""


# ── 의존성 함수 (Depends() 전용) ──

async def require_login(request: Request):
    """HTML 페이지용 로그인 체크 의존성."""
    if "user_no" not in request.session:
        raise LoginRequired()


async def api_require_login(request: Request):
    """JSON API용 로그인 체크 의존성 (Depends() 전용)."""
    if "user_no" not in request.session:
        raise ApiLoginRequired()


async def require_login_smart(request: Request):
    """페이지+API 혼합 라우터용 로그인 체크.
    미인증 시 API 요청(/api 경로 또는 JSON Accept)은 401 JSON,
    페이지 요청은 /login 리다이렉트."""
    if "user_no" in request.session:
        return
    if (request.url.path.startswith("/api")
            or "application/json" in request.headers.get("accept", "")):
        raise ApiLoginRequired()
    raise LoginRequired()


# ── 직접 호출용 헬퍼 ──

def get_login_user(request: Request) -> dict | None:
    """세션에서 로그인 사용자 정보 반환. 미로그인 시 None.
    async 엔드포인트에서 Depends() 없이 직접 인증 체크할 때 사용."""
    user_no = request.session.get('user_no')
    if not user_no:
        return None
    return {
        'user_no':   user_no,
        'user_id':   request.session.get('user_id', ''),
        'user_name': request.session.get('user_name', ''),
    }


def login_required_response() -> JSONResponse:
    """인증 실패 시 반환할 표준 401 응답."""
    return JSONResponse({'ok': False, 'error': '로그인이 필요합니다.'}, status_code=401)


# ── 세션 헬퍼 ──

def get_user_no(request: Request):
    return request.session.get("user_no")


def get_account_book_id(request: Request):
    return request.session.get("account_book_id", 2)
