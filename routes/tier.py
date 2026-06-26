"""routes/tier.py — 사용자 등급(role) 시스템 + AI 기능 게이트.

등급(낮음→높음): free < basic < premium < pro.  admin 은 운영자(사다리 밖, 전체 허용).
  - free   : 가입 기본. AI 기능 잠김.
  - basic  : 크레딧 충전 1회 이상 → 자동 승급(고정). 크레딧으로 AI 종량 사용.
  - premium: 구독 시 자동 승급. 구독 만료 시 basic 으로 강등.
  - pro    : 상위 구독 플랜. 〃
  - admin  : 운영자(수동 지정). 항상 전체 허용. 소유자(is_owner)도 게이트 우회.

등급은 'AI 기능 열림/잠김'만 결정한다. 크레딧 차감 상품은 등급과 무관하게 항상 차감한다.
구독 자동 승급(set_subscription_tier/expire_subscription)은 구독 결제 시스템 연동 시 호출.
"""
import logging

from fastapi import Request

from database.db_connection import get_db_connection

logger = logging.getLogger(__name__)

# 등급 순위(높을수록 상위). admin 은 별도 취급(항상 허용)이라 표에 두지 않는다.
TIER_RANK = {"free": 0, "basic": 1, "premium": 2, "pro": 3}
DEFAULT_TIER = "free"

# AI 기능별 최소 요구 등급(이상이면 사용 가능). 운영 중 자유롭게 조정 가능.
AI_FEATURE_MIN_TIER = {
    "chat":           "basic",    # AI 챗봇 (/api/chat/ask)
    "advisor":        "basic",    # 종목 AI 분석 (/stock/advisor/analyze)
    "recommend_pass": "premium",  # AI 추천 데이 패스 (/api/recommend-pass/enable)
}


class TierRequired(Exception):
    """현재 등급이 기능 요구 등급보다 낮음 → 403."""
    def __init__(self, need: str, have: str, feature: str = ""):
        self.need = need
        self.have = have
        self.feature = feature
        super().__init__(f"need={need} have={have} feature={feature}")


def _rank(tier) -> int:
    return TIER_RANK.get(tier or DEFAULT_TIER, 0)


def get_role_by_user_no(user_no) -> str:
    """DB 에서 회원 등급 조회. 미상/미존재면 free."""
    if not user_no:
        return DEFAULT_TIER
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM members WHERE id=%s", (user_no,))
            row = cur.fetchone()
    finally:
        conn.close()
    return (row and row.get("role")) or DEFAULT_TIER


def effective_role(request: Request) -> str:
    """게이트 판정용 등급. 항상 DB 기준(승급 직후/구독 웹훅 등 세션 staleness 회피).
    소유자는 admin 으로 간주."""
    from routes.utils import is_owner
    if is_owner(request):
        return "admin"
    return get_role_by_user_no(request.session.get("user_no"))


def has_tier(request: Request, min_tier: str) -> bool:
    role = effective_role(request)
    if role == "admin":
        return True
    return _rank(role) >= _rank(min_tier)


def require_feature(feature: str):
    """AI 기능 게이트 의존성 팩토리. 미로그인 → 401/redirect, 등급 부족 → 403(TierRequired).
    사용: @router.post(..., dependencies=[Depends(require_feature('chat'))])"""
    min_tier = AI_FEATURE_MIN_TIER.get(feature, "basic")

    async def _dep(request: Request):
        from routes.utils import ApiLoginRequired, LoginRequired
        if "user_no" not in request.session:
            if (request.url.path.startswith("/api")
                    or "application/json" in request.headers.get("accept", "")):
                raise ApiLoginRequired()
            raise LoginRequired()
        role = effective_role(request)
        if role == "admin":
            return
        if _rank(role) < _rank(min_tier):
            raise TierRequired(need=min_tier, have=role, feature=feature)

    return _dep


# ── 자동 승급/강등 ──

def _set_role(user_no, role: str) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE members SET role=%s WHERE id=%s", (role, user_no))
        conn.commit()
    finally:
        conn.close()


def promote_on_charge(user_no) -> str | None:
    """크레딧 충전 성공 시 호출. free 면 basic 으로 올린다(그 이상·admin 은 유지).
    승급했으면 새 등급 문자열, 변동 없으면 None 을 반환(호출자가 세션 갱신에 사용)."""
    try:
        cur_role = get_role_by_user_no(user_no)
        if cur_role != "admin" and _rank(cur_role) < _rank("basic"):
            _set_role(user_no, "basic")
            logger.info(f"[tier] user {user_no} 충전으로 basic 승급 (이전 {cur_role})")
            return "basic"
    except Exception as e:
        logger.error(f"[tier] promote_on_charge 실패 user {user_no}: {e}")
    return None


def set_subscription_tier(user_no, plan: str) -> None:
    """구독 활성화 시 호출(구독 결제 시스템 연동 예정). plan: 'premium'|'pro'.
    현재 등급보다 낮으면 올리지 않는다(강등은 expire_subscription 담당)."""
    plan = plan if plan in ("premium", "pro") else "premium"
    cur_role = get_role_by_user_no(user_no)
    if cur_role == "admin":
        return
    if _rank(cur_role) < _rank(plan):
        _set_role(user_no, plan)
        logger.info(f"[tier] user {user_no} 구독으로 {plan} 승급 (이전 {cur_role})")


def expire_subscription(user_no) -> None:
    """구독 만료/해지 시 호출. premium/pro 면 basic 으로 강등(충전 이력 가정)."""
    cur_role = get_role_by_user_no(user_no)
    if cur_role in ("premium", "pro"):
        _set_role(user_no, "basic")
        logger.info(f"[tier] user {user_no} 구독 만료로 basic 강등 (이전 {cur_role})")
