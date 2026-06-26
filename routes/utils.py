# routes/utils.py — FastAPI 공통 유틸리티
from fastapi import Request
from fastapi.responses import JSONResponse


# ── 커스텀 예외 (의존성에서 raise → 앱 레벨 핸들러가 처리) ──

class LoginRequired(Exception):
    """HTML 페이지 라우트: 미인증 → /login 리다이렉트."""

class ApiLoginRequired(Exception):
    """JSON API 라우트: 미인증 → 401 JSON."""

class OwnerOnly(Exception):
    """키움/KIS 주인 단일계좌 전용 엔드포인트에 비소유자가 접근 → 403 JSON."""


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


# ── 소유자(주인 단일계좌) 게이트 ──
# 키움/KIS는 집 PC의 단일 콜렉터(주인 계좌)에 묶여 있어, 실계좌·예수금·체결·실현손익·
# HTS 조건식은 '계정 소유자' 한 명의 사생활이다. 다중 유저 공개 배포 시 다른 유저가
# 이 데이터를 보지 못하도록 막는다. 시세/추천 등 시장 데이터는 게이트 대상이 아니다.

def get_owner_user_no():
    """단일 키움/KIS 계좌의 소유자 user_no. auto_jobs.get_owner_user_no 재사용
    (OWNER_USER_NO env 우선, 없으면 데이터 보유 회원 자동 탐지).
    공개 배포 시에는 OWNER_USER_NO 를 .env 에 명시하는 것을 강력 권장."""
    try:
        from auto_jobs import get_owner_user_no as _g
        return _g()
    except Exception:
        return None


def is_owner_user_no(user_no) -> bool:
    """주어진 user_no 가 계좌 소유자인지."""
    if not user_no:
        return False
    owner = get_owner_user_no()
    return owner is not None and int(user_no) == int(owner)


def is_owner(request: Request) -> bool:
    return is_owner_user_no(request.session.get("user_no"))


async def require_owner(request: Request):
    """주인 단일계좌 전용 의존성. 비로그인 → 401/redirect, 비소유자 → 403(OwnerOnly)."""
    if "user_no" not in request.session:
        if (request.url.path.startswith("/api")
                or "application/json" in request.headers.get("accept", "")):
            raise ApiLoginRequired()
        raise LoginRequired()
    if not is_owner(request):
        raise OwnerOnly()
