"""
notify/send.py
==============
카카오톡 "나에게 보내기" 발송. 토큰 자동 갱신 포함.

기능:
  - access_token 만료(6시간) 시 refresh_token으로 자동 재발급
  - 갱신된 토큰을 DB(app_settings)에 저장 — 멀티 프로세스 공유
  - DB 연결 실패 시 .env 파일로 폴백
  - 추천 JSON 읽어서 카톡 메시지로 포맷팅

사용:
  CLI 테스트:  python -m notify.send
  파이프라인:  from notify.send import send_daily_recommendation; send_daily_recommendation()
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

load_dotenv()

ROOT = Path(__file__).parent.parent
ENV_PATH = ROOT / ".env"
RECOMMEND_JSON = ROOT / "XGBoost_v2" / "model" / "daily_recommend.json"


# ─────────────────────────────────────────────────────────
# 토큰 관리 — DB 우선, .env 폴백
# ─────────────────────────────────────────────────────────

def _ensure_table() -> None:
    """app_settings, notify_history 테이블 없으면 생성."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    `key`       VARCHAR(100) PRIMARY KEY,
                    `value`     TEXT         NOT NULL,
                    updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
                                             ON UPDATE CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS notify_history (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    channel     VARCHAR(20)  NOT NULL DEFAULT 'kakao',
                    message     TEXT         NOT NULL,
                    ok          TINYINT(1)   NOT NULL DEFAULT 1,
                    error_msg   VARCHAR(255) DEFAULT NULL,
                    sent_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
    finally:
        conn.close()


_table_ready = False  # 프로세스 당 한 번만 CREATE TABLE


def _save_token(key: str, value: str) -> None:
    """토큰을 DB에 저장. 실패 시 .env 파일로 폴백."""
    global _table_ready
    os.environ[key] = value  # 현재 프로세스에 즉시 반영
    try:
        from database.db_connection import get_db_connection
        if not _table_ready:
            _ensure_table()
            _table_ready = True
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_settings (`key`, `value`) VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE `value` = VALUES(`value`), updated_at = NOW()
                    """,
                    (key, value),
                )
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[Token] DB 저장: {key}")
    except Exception as e:
        logger.error(f"[Token] DB 저장 실패, .env 폴백: {e}")
        _save_to_env(key, value)


def _load_token(key: str) -> Optional[str]:
    """DB에서 토큰 읽기. 없거나 실패 시 환경변수 반환."""
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT `value` FROM app_settings WHERE `key` = %s", (key,))
                row = cur.fetchone()
        finally:
            conn.close()
        if row:
            val = row["value"]
            os.environ[key] = val  # 프로세스 내 캐시
            return val
    except Exception:
        pass
    return os.getenv(key)  # DB 실패 시 env 반환


def _save_to_env(key: str, value: str) -> None:
    """.env 파일에 키-값 저장 (폴백용)."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    text = ENV_PATH.read_text(encoding="utf-8")
    line = f"{key}={value}"
    if re.search(rf"^{key}=", text, flags=re.MULTILINE):
        text = re.sub(rf"^{key}=.*$", line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + ("\n" if text and not text.endswith("\n") else "") + line + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    os.environ[key] = value


# 응답 본문에 되비칠 수 있는 자격증명 키 — 값만 가린다.
# `code` 는 넣지 않는다: 두 호출부 모두 인가코드를 보내지 않고(갱신은 grant_type=
# refresh_token, 발송은 template_object), 카카오 오류 응답의 `"code":-401` 만 걸려
# 진단 정보가 사라진다. 인가코드 교환은 kakao_auth.py(대화형 CLI)에만 있다.
_SECRET_IN_BODY = re.compile(
    r'("?(?:access_token|refresh_token|client_secret|client_id)"?\s*[:=]\s*"?)([^"\s,&}]+)',
    flags=re.IGNORECASE)


def _safe_body(resp: requests.Response) -> str:
    """실패 응답 본문을 로그·이력에 남길 수 있게 다듬는다.

    45cc7d6 으로 로그가 회전 파일에 영속되면서 실패 응답도 디스크에 남게 됐다.
    카카오 OAuth 오류 응답이 요청 파라미터를 되비추면 refresh_token·client_secret 이
    평문으로 박히므로, 토큰류 값을 가리고 200자로 자른다(_save_notify_history 가
    이미 쓰던 절단 폭과 같게 맞춘다).
    """
    return _SECRET_IN_BODY.sub(r"\1***", resp.text or "")[:200]


def _refresh_access_token() -> Optional[str]:
    """refresh_token으로 access_token 재발급."""
    rest_api_key   = os.getenv("KAKAO_REST_API_KEY")
    refresh_token  = _load_token("KAKAO_REFRESH_TOKEN")
    client_secret  = os.getenv("KAKAO_CLIENT_SECRET")  # 앱 보안 설정 활성 시 필요
    if not rest_api_key or not refresh_token:
        logger.error("❌ KAKAO_REST_API_KEY 또는 KAKAO_REFRESH_TOKEN 누락. notify.kakao_auth 먼저 실행하세요.")
        return None

    payload: dict = {
        "grant_type":    "refresh_token",
        "client_id":     rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=payload,
        timeout=10,
    )
    if resp.status_code != 200:
        logger.error(f"❌ 토큰 갱신 실패: {resp.status_code} {_safe_body(resp)}")
        return None

    data = resp.json()
    new_access = data.get("access_token")
    if new_access:
        _save_token("KAKAO_ACCESS_TOKEN", new_access)
        new_refresh = data.get("refresh_token")  # 만료 임박 시 함께 갱신
        if new_refresh:
            _save_token("KAKAO_REFRESH_TOKEN", new_refresh)
        logger.info("🔄 access_token 갱신 완료")
        return new_access
    return None


# ─────────────────────────────────────────────────────────
# 에러 알림
# ─────────────────────────────────────────────────────────
def notify_error(context: str, error: str) -> None:
    """에러 발생 시 카카오톡으로 즉시 알림. 실패해도 예외 미전파."""
    try:
        now = datetime.now().strftime("%m/%d %H:%M")
        msg = f"🚨 [{now}] 에러 발생\n\n📍 {context}\n\n{str(error)[:300]}"
        send_message_to_self(msg, link_url="http://localhost:8030")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# 메시지 발송
# ─────────────────────────────────────────────────────────
AI_DISCLAIMER = "⚠ AI 분석 · 참고용 · 투자 판단과 책임은 본인에게 있습니다"


def send_message_to_self(text: str, link_url: str = "http://localhost:8030/recommend",
                         ai_generated: bool = False) -> bool:
    """자기 자신에게 알림 발송. 기본 채널은 텔레그램(NOTIFY_CHANNEL=telegram).
    카카오 '나에게 보내기'는 알림 푸시가 오지 않아 텔레그램으로 전환됨.
    NOTIFY_CHANNEL=kakao 로 두면 기존 카카오 경로로 폴백.
    ai_generated=True 시 LLM 생성 콘텐츠 면책 문구를 자동으로 덧붙임."""
    channel = os.getenv("NOTIFY_CHANNEL", "telegram").lower()
    max_len = 4096 if channel == "telegram" else 1000

    if ai_generated and AI_DISCLAIMER not in text:
        # 면책 문구가 잘리지 않도록 본문을 먼저 자른 뒤 덧붙임
        limit = max_len - len(AI_DISCLAIMER) - 2
        text = text[:limit].rstrip() + "\n\n" + AI_DISCLAIMER

    if channel == "telegram":
        from notify.telegram import send_telegram
        return send_telegram(text, link_url)

    return _send_kakao(text, link_url)


def _send_kakao(text: str, link_url: str) -> bool:
    """카카오톡 '나에게 보내기' (레거시 폴백). 토큰 만료 시 자동 갱신 후 재시도."""
    access_token = _load_token("KAKAO_ACCESS_TOKEN")
    if not access_token:
        access_token = _refresh_access_token()
        if not access_token:
            return False

    template = {
        "object_type": "text",
        "text": text[:1000],  # 카톡 제한 1000자
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": "전체 보기",
    }

    def _post(token: str) -> requests.Response:
        return requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": json.dumps(template)},
            timeout=10,
        )

    resp = _post(access_token)

    # 401 = 토큰 만료. 자동 갱신 후 재시도.
    if resp.status_code == 401:
        logger.warning("⚠ access_token 만료, 갱신 시도...")
        new_token = _refresh_access_token()
        if not new_token:
            return False
        resp = _post(new_token)

    ok = resp.status_code == 200
    err_msg = None if ok else f"{resp.status_code} {_safe_body(resp)}"
    _save_notify_history("kakao", text, ok, err_msg)

    if ok:
        logger.info("✅ 카카오톡 발송 성공")
        return True
    logger.error(f"❌ 카카오톡 발송 실패: {resp.status_code} {_safe_body(resp)}")
    return False


def _save_notify_history(channel: str, message: str, ok: bool, error_msg: Optional[str] = None) -> None:
    """발송 결과를 DB notify_history 테이블에 저장. 실패해도 예외 미전파."""
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notify_history (channel, message, ok, error_msg)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (channel, message[:1000], 1 if ok else 0, error_msg),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# 초기 토큰 마이그레이션 (.env → DB)
# ─────────────────────────────────────────────────────────

def migrate_tokens_to_db() -> None:
    """
    .env에 저장된 카카오 토큰을 DB로 이전.
    이미 DB에 있으면 건너뜀.
    app 최초 기동 시 또는 수동으로 한 번 호출하면 됨.
    """
    for key in ("KAKAO_ACCESS_TOKEN", "KAKAO_REFRESH_TOKEN"):
        env_val = os.getenv(key)
        if not env_val:
            continue
        try:
            from database.db_connection import get_db_connection
            _ensure_table()
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT `value` FROM app_settings WHERE `key` = %s", (key,))
                    row = cur.fetchone()
                if not row:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO app_settings (`key`, `value`) VALUES (%s, %s)",
                            (key, env_val),
                        )
                    conn.commit()
                    logger.info(f"[Token] 마이그레이션 완료: {key}")
                else:
                    logger.info(f"[Token] 이미 DB에 존재: {key}")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[Token] 마이그레이션 실패 ({key}): {e}")


def sync_tokens_from_env() -> None:
    """
    .env의 카카오 토큰을 DB에 강제 덮어쓰기.
    kakao_auth.py로 새 토큰 발급 후 호출하면 DB와 동기화됨.
    """
    for key in ("KAKAO_ACCESS_TOKEN", "KAKAO_REFRESH_TOKEN"):
        env_val = os.getenv(key)
        if not env_val:
            continue
        _save_token(key, env_val)
        logger.info(f"[Token] DB 동기화: {key}")


# ─────────────────────────────────────────────────────────
# 메시지 포맷팅
# ─────────────────────────────────────────────────────────
def _format_picks(picks: list, max_show: int = 5) -> str:
    """추천 종목 리스트 → 한 줄씩 포맷."""
    if not picks:
        return "  (추천 없음)"
    lines = []
    for r in picks[:max_show]:
        lines.append(
            f"  • {r['name']} ({r['code']})\n"
            f"    현재 {r['price']:,}원 → 목표 {r['target']:,} / 손절 {r['stop']:,}\n"
            f"    신뢰도 {r['confidence'] * 100:.0f}%"
        )
    return "\n".join(lines)


def build_message(data: dict) -> str:
    """추천 JSON을 카톡 메시지 텍스트로 변환."""
    base_date = data.get("base_date", "")
    daily = data.get("daily", [])
    short = data.get("short", [])
    swing = data.get("swing", [])

    return (
        f"📊 오늘의 추천 종목 ({base_date})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"\n🔥 데일리 (3일 +2%)\n"
        f"{_format_picks(daily, max_show=3)}\n"
        f"\n📈 단타 (5일 +3%)\n"
        f"{_format_picks(short, max_show=3)}\n"
        f"\n📊 스윙 (14일 +7%)\n"
        f"{_format_picks(swing, max_show=3)}\n"
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"⚠ 참고용. 투자 책임은 본인.\n"
        f"전체 목록은 아래 버튼"
    )


# ─────────────────────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────────────────────
def send_daily_recommendation() -> bool:
    """daily_recommend.json 읽어서 카톡 발송."""
    if not RECOMMEND_JSON.exists():
        print(f"❌ {RECOMMEND_JSON} 없음. 먼저 'python -m XGBoost_v2.daily_recommend' 실행 필요.")
        return False

    try:
        with open(RECOMMEND_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ JSON 읽기 실패: {e}")
        return False

    msg = build_message(data)
    print("\n========== 발송 메시지 ==========")
    print(msg)
    print("================================\n")
    return send_message_to_self(msg, ai_generated=True)  # ML 추천 — 면책 문구 자동 부착


if __name__ == "__main__":
    send_daily_recommendation()