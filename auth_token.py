"""
auth_token.py — Bearer 토큰 인증(모바일/Capacitor 앱용).

웹은 기존 쿠키 세션(SessionMiddleware)을 그대로 쓰고, Capacitor WebView 앱은
서드파티 쿠키가 막혀 세션이 깨지므로 `Authorization: Bearer <token>` 으로 인증한다.

PyJWT/python-jose 는 미설치라 itsdangerous 의 서명 토큰을 쓴다(만료 포함).
BearerAuthMiddleware 는 세션에 user_no 가 없을 때만 Bearer 토큰을 읽어
세션 스코프에 user_no/user_id/user_name/role 을 주입한다 → 기존
`request.session['user_no']` 기반 호출부가 코드 변경 없이 동작한다(하위호환).
"""
import logging

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.types import ASGIApp, Receive, Scope, Send

from config import Config

logger = logging.getLogger(__name__)

_SALT = "auth-bearer-v1"
TOKEN_MAX_AGE = 60 * 60 * 24 * 30   # 30일

_serializer = URLSafeTimedSerializer(Config.SECRET_KEY, salt=_SALT)


def make_token(user_no: int, user_id: str, user_name: str, role: str) -> str:
    """로그인 성공 시 발급할 서명 토큰."""
    return _serializer.dumps({
        "user_no":   user_no,
        "user_id":   user_id,
        "user_name": user_name,
        "role":      role,
    })


def read_token(token: str, max_age: int = TOKEN_MAX_AGE) -> dict | None:
    """토큰 검증·복호화. 만료/위조 시 None."""
    try:
        return _serializer.loads(token, max_age=max_age)
    except SignatureExpired:
        logger.info("[auth_token] 만료된 토큰")
        return None
    except BadSignature:
        logger.warning("[auth_token] 위조/손상 토큰")
        return None
    except Exception as e:
        logger.warning(f"[auth_token] 토큰 파싱 실패: {e}")
        return None


class BearerAuthMiddleware:
    """
    세션에 user_no 가 없고 Authorization: Bearer 토큰이 유효하면
    세션 스코프에 사용자 정보를 주입한다. SessionMiddleware 안쪽(inner)에
    위치해야 scope['session'] 을 볼 수 있다 → app.py 에서 SessionMiddleware
    보다 먼저 add_middleware 로 등록한다(먼저 등록=더 안쪽).
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        session = scope.get("session")
        if session is not None and not session.get("user_no"):
            auth = None
            for k, v in scope.get("headers", []):
                if k == b"authorization":
                    auth = v.decode("latin-1")
                    break
            if auth and auth.lower().startswith("bearer "):
                payload = read_token(auth[7:].strip())
                if payload and payload.get("user_no"):
                    session["user_no"]   = payload["user_no"]
                    session["user_id"]   = payload.get("user_id")
                    session["user_name"] = payload.get("user_name")
                    session["role"]      = payload.get("role") or "free"

        await self.app(scope, receive, send)
