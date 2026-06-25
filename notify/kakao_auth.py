"""
notify/kakao_auth.py
====================
카카오톡 토큰을 최초 1회 발급받는 스크립트.

사용 절차:
  1. .env 에 KAKAO_REST_API_KEY=xxx 추가
  2. python -m notify.kakao_auth 실행
  3. 안내에 따라 브라우저에서 로그인 → 리디렉션된 URL의 code 파라미터 복사
  4. 터미널에 붙여넣으면 access_token / refresh_token이 .env에 자동 추가됨

이 스크립트는 한 번만 실행하면 됩니다.
이후 토큰 자동 갱신은 send.py에서 처리.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlencode
import requests
from dotenv import load_dotenv

load_dotenv()

REDIRECT_URI = "https://localhost.com"  # Kakao Developers에 등록한 것과 동일해야 함


def main():
    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    client_secret = os.getenv("KAKAO_CLIENT_SECRET", "")
    if not rest_api_key:
        print("❌ .env 에 KAKAO_REST_API_KEY=... 를 먼저 추가하세요.")
        return

    # 1단계: 인증 URL 출력
    auth_url = "https://kauth.kakao.com/oauth/authorize?" + urlencode({
        "response_type": "code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "scope": "talk_message",
    })
    print("\n[1] 아래 URL을 브라우저에 복붙해서 열고, 카카오 로그인 + 동의를 눌러주세요.")
    print(auth_url)
    print("\n[2] 로그인이 끝나면 'localhost.com/?code=XXXXXXXX...' 형태로 리디렉션됩니다.")
    print("    페이지가 안 떠도 URL 자체는 주소창에 보일 거예요.")
    print("    그 URL의 'code=' 뒤 부분만 복사해서 아래에 붙여넣으세요.\n")

    code = input("code 값: ").strip()
    if not code:
        print("❌ code 값이 비었습니다.")
        return

    # 2단계: code → access_token / refresh_token 교환
    print("\n[3] 토큰 발급 중...")
    token_data = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    if client_secret:
        token_data["client_secret"] = client_secret
    resp = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=token_data,
        timeout=10,
    )

    if resp.status_code != 200:
        print(f"❌ 토큰 발급 실패: {resp.status_code} {resp.text}")
        return

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token or not refresh_token:
        print(f"❌ 응답에 토큰이 없습니다: {data}")
        return

    print("✅ 토큰 발급 성공!")
    print(f"  access_token  유효시간: {data.get('expires_in')}초 (약 {data.get('expires_in', 0) // 3600}시간)")
    print(f"  refresh_token 유효시간: {data.get('refresh_token_expires_in')}초 (약 {data.get('refresh_token_expires_in', 0) // 86400}일)")

    # 3단계: .env 파일에 저장
    env_path = Path(".env")
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")
    text = env_path.read_text(encoding="utf-8")

    def upsert(key: str, value: str, body: str) -> str:
        line = f"{key}={value}"
        if re.search(rf"^{key}=", body, flags=re.MULTILINE):
            return re.sub(rf"^{key}=.*$", line, body, flags=re.MULTILINE)
        return body.rstrip() + ("\n" if body and not body.endswith("\n") else "") + line + "\n"

    text = upsert("KAKAO_ACCESS_TOKEN", access_token, text)
    text = upsert("KAKAO_REFRESH_TOKEN", refresh_token, text)
    env_path.write_text(text, encoding="utf-8")
    os.environ["KAKAO_ACCESS_TOKEN"] = access_token
    os.environ["KAKAO_REFRESH_TOKEN"] = refresh_token

    # DB에도 즉시 동기화
    try:
        from notify.send import sync_tokens_from_env
        sync_tokens_from_env()
        print(f"\n✅ .env + DB 토큰 저장 완료. 이제 'python -m notify.send'로 테스트해보세요.")
    except Exception as e:
        print(f"\n✅ .env 토큰 저장 완료 (DB 동기화 실패: {e}). 'python -m notify.send'로 테스트해보세요.")


if __name__ == "__main__":
    main()