"""
notify/telegram_bot.py
======================
텔레그램 양방향 폴링 — AI 챗봇(마켓 코파일럿, Claude 유료).

롱폴링(getUpdates)으로 수신하므로 공개 HTTPS 콜백/원격접속이 필요 없다
(서버가 127.0.0.1 전용이어도 동작). 인가된 사용자(TELEGRAM_CHAT_ID, 소유자)만 응답.

수신 메시지는 agent/claude_chat.py 로 전달되어 Claude 답변을 생성하며,
호출 1회당 고정 크레딧(Config.CHAT_CREDIT_COST)을 차감한다. ANTHROPIC_API_KEY 가
없으면 챗봇은 비활성으로 안내한다. 아웃바운드 알림(notify/send.py)은 정상 동작.

서버 시작 시 app.py 가 start_polling() 으로 데몬 스레드 기동.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

from notify.send import _load_token
from notify.telegram import _api, API_BASE

logger = logging.getLogger(__name__)
_started = False

HELP_TEXT = (
    "📈 마켓 코파일럿 봇입니다. 국내외 시장·종목·내 포트폴리오를 물어보세요.\n"
    "예) '코스피 어때', '삼성전자 분석', '내 종목 손익', '간밤 미국증시'\n"
    "· 답변은 실시간 데이터 근거이며 출처·시각을 함께 표기합니다.\n"
    "· 확인 안 된 정보는 추측하지 않습니다."
)


def _get_updates(token: str, offset: int | None, timeout: int = 25):
    """롱폴링 getUpdates. requests 타임아웃은 텔레그램 타임아웃보다 길게."""
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(API_BASE.format(token=token, method="getUpdates"),
                        params=params, timeout=timeout + 10)
    return resp.json()


def _handle(text: str, chat_id: str, token: str):
    t = (text or "").strip()
    if not t:
        return
    if t in ("/start", "/help", "도움말"):
        _api("sendMessage", token, chat_id=chat_id, text=HELP_TEXT, disable_web_page_preview="true")
        return

    from agent.claude_chat import chat as claude_chat, is_enabled
    if not is_enabled():
        _api("sendMessage", token, chat_id=chat_id,
             text="🤖 AI 챗봇이 아직 설정되지 않았습니다(API 키 없음).",
             disable_web_page_preview="true")
        return

    # 크레딧을 차감할 대상(소유자) 식별
    from auto_jobs import get_owner_user_no
    user_no = get_owner_user_no()
    if not user_no:
        _api("sendMessage", token, chat_id=chat_id, text="사용자 정보를 찾을 수 없습니다.")
        return

    _api("sendChatAction", token, chat_id=chat_id, action="typing")
    r = claude_chat(t, int(user_no))   # 성공 시에만 호출당 고정 차감
    if r.get("ok"):
        answer = (r.get("answer") or "").strip()
        footer = f"\n\n— 사용 {r.get('cost', 0):,}C · 잔액 {r.get('balance', 0):,}C"
        _api("sendMessage", token, chat_id=chat_id,
             text=(answer + footer)[:4096], disable_web_page_preview="true")
    else:
        _api("sendMessage", token, chat_id=chat_id,
             text="⚠ " + (r.get("error") or "답변을 생성하지 못했습니다."),
             disable_web_page_preview="true")


def _loop():
    token = _load_token("TELEGRAM_BOT_TOKEN")
    auth_chat = str(_load_token("TELEGRAM_CHAT_ID") or "")
    if not token:
        logger.info("[telegram_bot] 토큰 없음 — 양방향 폴링 비활성화")
        return
    if not auth_chat:
        # fail-closed: 인가 chat 미설정 상태로 폴링하면 아무나 명령 가능
        logger.warning("[telegram_bot] TELEGRAM_CHAT_ID 미설정 — 양방향 폴링 시작 거부 (fail-closed)")
        return
    logger.info("[telegram_bot] 양방향 챗봇 폴링 시작")

    # 시작 시 그동안 쌓인 과거 메시지는 건너뛴다(재시작 시 폭주 방지)
    offset = None
    try:
        js = _get_updates(token, None, timeout=0)
        if js and js.get("ok") and js.get("result"):
            offset = js["result"][-1]["update_id"] + 1
    except Exception:
        pass

    while True:
        try:
            js = _get_updates(token, offset, timeout=25)
            if not js or not js.get("ok"):
                time.sleep(3)
                continue
            for upd in js.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message") or {}
                chat = msg.get("chat") or {}
                cid = str(chat.get("id") or "")
                text = msg.get("text") or ""
                if not text:
                    continue
                # 인가된 소유자만 응답 (API 비용·보안) — fail-closed:
                # 인가 chat 미설정이거나 불일치면 무조건 거부
                if not auth_chat or cid != auth_chat:
                    logger.warning(f"[telegram_bot] 미인가 chat {cid} 무시")
                    continue
                try:
                    _handle(text, cid, token)
                except Exception as e:
                    logger.error(f"[telegram_bot] 처리 오류: {e}", exc_info=True)
                    try:
                        _api("sendMessage", token, chat_id=cid,
                             text="⚠ 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
                    except Exception:
                        pass
        except requests.exceptions.ReadTimeout:
            continue   # 롱폴링 정상 타임아웃
        except Exception as e:
            logger.error(f"[telegram_bot] 폴링 오류: {e}")
            time.sleep(5)


def start_polling():
    """데몬 스레드로 폴링 시작. 토큰 없으면 조용히 미동작. 중복 호출 방지."""
    global _started
    if _started:
        return
    if not _load_token("TELEGRAM_BOT_TOKEN"):
        logger.info("[telegram_bot] TELEGRAM_BOT_TOKEN 미설정 — 양방향 챗봇 비활성화")
        return
    if not str(_load_token("TELEGRAM_CHAT_ID") or ""):
        # fail-closed: 인가 chat 없이 폴링을 시작하면 모든 chat의 명령이 처리될 수 있음
        logger.warning("[telegram_bot] TELEGRAM_CHAT_ID 미설정 — 양방향 챗봇을 시작하지 않습니다 (fail-closed)")
        return
    _started = True
    threading.Thread(target=_loop, name="telegram_bot", daemon=True).start()
