"""
bot/kiwoom_watchdog.py
======================
키움 32비트 콜렉터(포트 5100) 헬스체크 + 자동 재시작.

기능:
  - 30초마다 http://127.0.0.1:5100/status 응답 체크
  - 무응답 시 start_kiwoom_32bit.bat 재실행
  - 재시작 성공/실패 카카오톡 알림
  - 한 세션 최대 5회 재시작 (초과 시 알림 후 대기)

실행:
  python bot/kiwoom_watchdog.py
  start_watchdog.bat
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).parent.parent / ".env")

KIWOOM_URL     = f"http://127.0.0.1:{os.getenv('KIWOOM_COLLECTOR_PORT', '5100')}"
BAT_FILE       = Path(__file__).parent.parent / "start_kiwoom_32bit.bat"
CHECK_INTERVAL = 30    # 헬스체크 주기 (초)
BOOT_TIMEOUT   = 60    # 재시작 후 응답 대기 최대 시간 (초)
MAX_RESTARTS   = 5     # 세션당 최대 자동 재시작 횟수

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent.parent / "logs" / "kiwoom_watchdog.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("kiwoom_watchdog")

_restart_count = 0


def _is_alive() -> bool:
    try:
        r = requests.get(f"{KIWOOM_URL}/status", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _notify(msg: str) -> None:
    try:
        from notify.telegram import send_telegram
        send_telegram(msg)
    except Exception as e:
        logger.error(f"텔레그램 알림 실패: {e}")


def _restart() -> bool:
    """BAT 파일로 키움 워커를 새 콘솔 창에서 재시작. 성공 여부 반환."""
    global _restart_count

    if _restart_count >= MAX_RESTARTS:
        msg = (
            f"⛔ 키움 워커 자동 재시작 {MAX_RESTARTS}회 한도 초과\n"
            "수동으로 start_kiwoom_32bit.bat 실행 필요"
        )
        logger.error(msg)
        _notify(msg)
        return False

    _restart_count += 1
    logger.info("키움 워커 재시작 시도 [%d/%d]", _restart_count, MAX_RESTARTS)

    try:
        subprocess.Popen(
            ["cmd", "/c", str(BAT_FILE)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception as e:
        logger.error(f"재시작 명령 실패: {e}")
        return False

    # 응답이 돌아올 때까지 최대 BOOT_TIMEOUT 초 대기
    for _ in range(BOOT_TIMEOUT // 5):
        time.sleep(5)
        if _is_alive():
            msg = f"✅ 키움 워커 재시작 완료 ({_restart_count}회차)"
            logger.info(msg)
            _notify(msg)
            return True

    logger.warning("재시작 후에도 응답 없음")
    return False


def run() -> None:
    Path(__file__).parent.parent.joinpath("logs").mkdir(exist_ok=True)

    logger.info("=" * 45)
    logger.info("  키움 워커 감시 시작")
    logger.info("  체크 주기: %d초  |  최대 재시작: %d회", CHECK_INTERVAL, MAX_RESTARTS)
    logger.info("=" * 45)

    was_alive = _is_alive()
    if was_alive:
        logger.info("키움 워커 정상 확인")
    else:
        logger.warning("키움 워커 미응답 상태에서 감시 시작")

    while True:
        time.sleep(CHECK_INTERVAL)
        alive = _is_alive()

        if not alive and was_alive:
            # 방금 다운됨
            msg = "🚨 키움 워커 응답 없음 — 자동 재시작 시도"
            logger.warning(msg)
            _notify(msg)
            _restart()

        elif not alive and not was_alive:
            # 계속 다운 중 (재시작 실패 상태)
            logger.info("키움 워커 여전히 미응답")

        elif alive and not was_alive:
            # 외부에서 직접 켜진 경우
            logger.info("키움 워커 복구 감지")
            _restart_count = 0  # 카운터 초기화

        was_alive = alive


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("감시 종료")
    except Exception as e:
        logger.error(f"감시 비정상 종료: {e}", exc_info=True)
        _notify(f"🚨 kiwoom_watchdog 비정상 종료: {e}")
        raise
