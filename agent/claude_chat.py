"""agent/claude_chat.py — 최소 Claude 챗봇 (호출당 고정 크레딧 차감).

파일럿 버전: 시장 데이터 도구(tool-calling) 없이, 사용자 질문을 Claude에 그대로
전달하고 한국어 답변을 돌려준다. 호출 1회당 Config.CHAT_CREDIT_COST 만큼 크레딧을
차감한다.

차감 정책
---------
1) 호출 전 잔액이 비용 미만이면 Claude를 부르지 않고 거절(돈 아낌).
2) Claude 호출이 실패하면 차감하지 않는다.
3) 호출이 성공한 뒤에만 고정 비용을 차감한다.

키(ANTHROPIC_API_KEY)가 없으면 챗봇은 비활성으로 응답한다.
"""
import logging

from config import Config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "당신은 한국 투자자를 돕는 '마켓 코파일럿' 챗봇입니다. 국내외 주식시장과 투자 개념을 "
    "한국어로 친절하고 간결하게 설명합니다.\n"
    "중요 원칙:\n"
    "1. 이 파일럿 버전에는 실시간 시세·뉴스 조회 도구가 없습니다. 따라서 '지금 가격', "
    "'오늘 종가' 같은 실시간 수치는 알 수 없습니다. 모르는 최신 수치는 지어내지 말고, "
    "'실시간 데이터는 조회할 수 없다'고 솔직히 밝히세요.\n"
    "2. 일반적인 개념·전략·용어 설명, 시장 구조 해설은 도와줄 수 있습니다.\n"
    "3. 투자 권유가 아니라 정보 제공입니다. 최종 판단·책임은 사용자에게 있음을 적절히 환기하세요."
)


def is_enabled() -> bool:
    """Claude 키가 설정돼 있으면 챗봇 사용 가능."""
    return bool(Config.ANTHROPIC_API_KEY)


def chat(message: str, user_no: int) -> dict:
    """질문을 받아 Claude 답변을 생성하고 고정 크레딧을 차감한다.

    반환: {ok: bool, answer?: str, error?: str, cost?: int, balance?: int}
    """
    text = (message or "").strip()
    if not text:
        return {"ok": False, "error": "질문 내용이 비어 있습니다."}

    if not is_enabled():
        return {"ok": False, "error": "AI 챗봇이 설정되지 않았습니다(API 키 없음)."}

    cost = Config.CHAT_CREDIT_COST

    # 1) 호출 전 잔액 확인 — 부족하면 Claude 호출 자체를 안 함
    from routes.credits import get_balance_value
    bal = get_balance_value(user_no)
    if bal < cost:
        return {"ok": False,
                "error": f"크레딧이 부족합니다. (필요 {cost:,}C / 보유 {bal:,}C)\n"
                         f"내 정보 → 크레딧/충전에서 충전해 주세요.",
                "cost": cost, "balance": bal}

    # 2) Claude 호출 (실패 시 차감하지 않음)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=Config.CHAT_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        answer = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
        if not answer:
            return {"ok": False, "error": "답변을 생성하지 못했습니다. 다시 시도해 주세요."}
    except Exception as e:
        logger.error(f"[claude_chat] Claude 호출 오류: {e}", exc_info=True)
        return {"ok": False, "error": "일시적인 오류로 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."}

    # 3) 성공 후 고정 차감
    from routes.credits import deduct_credits
    d = deduct_credits(user_no, cost, memo="AI 챗봇 1회")
    new_bal = d.get("balance")
    return {"ok": True, "answer": answer, "cost": cost, "balance": new_bal}
