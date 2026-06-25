"""
notify/telegram.py
==================
텔레그램 봇 메시지 발송. 카카오 "나에게 보내기"는 알림 푸시가 오지 않아
모든 알림을 텔레그램으로 전환하기 위한 모듈.

토큰/채팅ID 저장은 notify.send 의 DB(app_settings) 헬퍼를 재사용한다.
  - TELEGRAM_BOT_TOKEN : @BotFather 로 봇 생성 시 받는 토큰
  - TELEGRAM_CHAT_ID   : 봇과의 대화 chat id (--setup 으로 자동 탐색)

설정 (최초 1회):
  1) 텔레그램에서 @BotFather → /newbot → 토큰 확보
  2) python -m notify.telegram --token <봇토큰>
  3) 텔레그램에서 만든 봇을 찾아 아무 메시지나 전송 (예: "hi")
  4) python -m notify.telegram --setup        # chat_id 자동 탐색·저장 + 테스트 발송

사용:
  from notify.telegram import send_telegram
  send_telegram("메시지", link_url="https://...")
"""
from __future__ import annotations

import os
from typing import Optional

import requests

# DB(app_settings) 토큰 저장/조회·이력 기록은 send.py 의 검증된 헬퍼 재사용
from notify.send import _load_token, _save_token, _save_notify_history

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api(method: str, token: str, **data) -> Optional[dict]:
    try:
        resp = requests.post(API_BASE.format(token=token, method=method), data=data, timeout=10)
        js = resp.json()
        if not js.get("ok"):
            print(f"[Telegram] {method} 실패: {resp.status_code} {str(js)[:200]}")
            return None
        return js
    except Exception as e:
        print(f"[Telegram] {method} 호출 오류: {e}")
        return None


def send_telegram(text: str, link_url: Optional[str] = None) -> bool:
    """텔레그램 봇으로 메시지 발송. 성공 시 True. notify_history 에 기록."""
    token   = _load_token("TELEGRAM_BOT_TOKEN")
    chat_id = _load_token("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("❌ TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 누락. `python -m notify.telegram --setup` 먼저 실행.")
        _save_notify_history("telegram", text, False, "missing token/chat_id")
        return False

    body = text if not link_url else f"{text}\n\n🔗 {link_url}"
    # 텍스트 모드(parse_mode 미사용) — 본문의 +,*,_,━ 등 특수문자 파싱오류 방지.
    # 본문 내 순수 URL 은 텔레그램이 자동 링크 처리.
    js = _api("sendMessage", token,
              chat_id=chat_id, text=body[:4096], disable_web_page_preview="true")
    ok = js is not None
    _save_notify_history("telegram", text, ok, None if ok else "send failed")
    if ok:
        print("✅ 텔레그램 발송 성공")
    return ok


def discover_chat_id() -> Optional[str]:
    """getUpdates 로 가장 최근에 봇에게 보낸 사용자의 chat_id 를 탐색."""
    token = _load_token("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ 먼저 토큰을 저장하세요: python -m notify.telegram --token <봇토큰>")
        return None
    js = _api("getUpdates", token)
    if not js:
        return None
    results = js.get("result", []) or []
    if not results:
        print("⚠ 받은 메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지나 먼저 보내세요.")
        return None
    # 가장 최근 업데이트의 chat id
    for upd in reversed(results):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is not None:
            name = chat.get("username") or chat.get("first_name") or ""
            print(f"[Telegram] chat_id 탐색: {cid} ({name})")
            return str(cid)
    print("⚠ chat_id 를 찾지 못했습니다.")
    return None


def setup() -> bool:
    """chat_id 자동 탐색·저장 후 테스트 메시지 발송."""
    cid = discover_chat_id()
    if not cid:
        return False
    _save_token("TELEGRAM_CHAT_ID", cid)
    print(f"[Telegram] TELEGRAM_CHAT_ID 저장 완료: {cid}")
    return send_telegram("✅ 텔레그램 알림 연결 완료 — 이제 모든 알림이 여기로 옵니다.")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--token" in args:
        tok = args[args.index("--token") + 1]
        _save_token("TELEGRAM_BOT_TOKEN", tok)
        print("✅ TELEGRAM_BOT_TOKEN 저장 완료. 이제 봇에게 메시지를 보낸 뒤 --setup 을 실행하세요.")
    elif "--setup" in args:
        setup()
    elif "--test" in args:
        send_telegram("🔔 테스트 메시지 (notify.telegram --test)")
    else:
        print("사용법:\n"
              "  python -m notify.telegram --token <봇토큰>\n"
              "  python -m notify.telegram --setup\n"
              "  python -m notify.telegram --test")
