"""
daily_pipeline.py
=================
매일 아침 자동 실행되는 파이프라인.
  1. 추천 생성 (XGBoost_v2.daily_recommend.run_daily)
  2. 카카오톡 발송 (notify.send.send_daily_recommendation)

Windows 작업 스케줄러가 run_daily_recommend.bat → 이 파일 실행하는 구조.

수동 테스트:
  python daily_pipeline.py
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"daily_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log = logging.getLogger("pipeline")

    log.info("=" * 50)
    log.info("일일 파이프라인 시작")
    log.info("=" * 50)

    # 1) 추천 생성
    try:
        from XGBoost_v2.daily_recommend import run_daily
        log.info("[1/4] 추천 생성 시작")
        result = run_daily(top=15, min_conf=0.20, universe_size=200, save_txt=False)
        if not result.get("ok"):
            err = result.get("error", "알 수 없는 오류")
            log.error(f"추천 생성 실패: {err}")
            try:
                from notify.send import notify_error
                notify_error("daily_pipeline — 추천 생성", err)
            except Exception:
                pass
            return 1
        log.info(f"[1/4] 추천 생성 완료: BUY {result['n_buy']}개")
    except Exception as e:
        log.exception(f"추천 생성 중 예외: {e}")
        try:
            from notify.send import notify_error
            notify_error("daily_pipeline — 추천 생성 예외", str(e))
        except Exception:
            pass
        return 1

    # 2) 카톡 발송
    try:
        from notify.send import send_daily_recommendation
        log.info("[2/4] 카톡 발송 시작")
        ok = send_daily_recommendation()
        if not ok:
            log.warning("⚠ 카톡 발송 실패 - 토큰 만료 또는 카카오 설정 문제. 추천은 정상 저장됨.")
        else:
            log.info("[2/4] 카톡 발송 완료")
    except Exception as e:
        log.exception(f"카톡 발송 중 예외 (추천은 정상 저장됨): {e}")

    # 3) 가상매매 신규 등록
    try:
        from bot.paper_trading import open_new_trades
        log.info("[3/4] 가상매매 신규 종목 등록 시작")
        opened = open_new_trades()
        log.info(f"[3/4] 가상매매 신규 등록: {opened}개")
    except Exception as e:
        log.exception(f"가상매매 등록 중 예외 (파이프라인 계속): {e}")

    # 4) 가상매매 진행중 거래 체크
    check_result = {}
    try:
        from bot.paper_trading import check_open_trades
        log.info("[4/4] 가상매매 진행중 거래 체크 시작")
        check_result = check_open_trades()
        log.info(f"[4/4] 가상매매 체크 완료: {check_result}")
    except Exception as e:
        log.exception(f"가상매매 체크 중 예외 (파이프라인 계속): {e}")

    # 5) 가상매매 청산 결과 카톡 알림
    try:
        hit     = check_result.get("hit", 0)
        stop    = check_result.get("stop", 0)
        timeout = check_result.get("timeout", 0)
        closed  = hit + stop + timeout
        if closed > 0:
            from bot.paper_trading import get_summary
            from notify.send import send_message_to_self
            summary = get_summary()
            msg = (
                f"📊 가상매매 일일 리포트\n"
                f"─────────────────\n"
                f"오늘 청산: {closed}건\n"
                f"  🎯 목표달성: {hit}건\n"
                f"  🚨 손절: {stop}건\n"
                f"  ⏰ 기간만료: {timeout}건\n"
                f"─────────────────\n"
                f"누적 승률: {summary['win_rate']:.1f}%\n"
                f"평균 순수익률: {summary.get('avg_net_return', summary['avg_return']):+.2f}%"
            )
            send_message_to_self(msg)
            log.info("[5/5] 가상매매 청산 알림 발송 완료")
    except Exception as e:
        log.warning(f"가상매매 알림 발송 실패 (파이프라인 계속): {e}")

    log.info("✅ 파이프라인 정상 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())