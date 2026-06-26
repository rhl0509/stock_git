"""routes/chat.py — 브라우저용 AI 챗봇 (Claude 유료, 호출당 고정 크레딧 차감).

마이페이지에서 충전한 크레딧으로 바로 대화·차감을 확인할 수 있게 한다.
실제 답변/차감 로직은 agent/claude_chat.py 가 담당한다(텔레그램 봇과 동일 경로).
"""
import logging

from fastapi import APIRouter, Request, Body, Depends
from fastapi.responses import JSONResponse

from routes.tier import require_feature

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('/api/chat/ask', dependencies=[Depends(require_feature('chat'))])
def ask(request: Request, data: dict = Body(default={})):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    message = (data.get('message') or '').strip()
    if not message:
        return JSONResponse({"error": "질문을 입력하세요."}, status_code=400)

    from agent.claude_chat import chat as claude_chat
    r = claude_chat(message, request.session['user_no'])
    # 잔액 부족 등은 ok=False 로 그대로 반환(프론트가 표시). HTTP 200 유지.
    return JSONResponse(r)
