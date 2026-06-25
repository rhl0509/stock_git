"""
agent/gap_risk.py
=================
Layer 1 — 장전 갭하락 위험 경보 (코스피 급락의 '시간 단위' 선행 신호).

코스피 급락의 상당수는 간밤 미국증시·새벽 지수선물에서 먼저 예고된다.
장 시작 전(08:35)에 간밤 흐름으로 '오늘 갭하락 위험 등급'을 산출해 텔레그램으로
미리 알리고, 위험 등급이 높으면 보유종목 손절가를 장 시작 전에 자동 무장한다.

선행 신호:
  - 나스닥/S&P 간밤 등락 (yfinance, 전일 종가 대비)
  - 나스닥/S&P 지수선물(NQ=F, ES=F) 야간 변동 — 개장 직전 분위기 반영(가장 신선)
  - VIX 수준 (변동성 레짐)

등급(가장 큰 낙폭 기준 OR VIX):
  관심 ★   : 낙폭 <= -1.2%  또는 VIX >= 24
  주의 ★★  : 낙폭 <= -2.0%  또는 VIX >= 30   → 손절가 자동 무장
  경계 ★★★ : 낙폭 <= -3.0%  또는 VIX >= 38   → 손절가 자동 무장

스케줄: 평일 08:35 (agent/scheduler.py 의 _job_gap_risk)
수동:   python -m agent.gap_risk
"""
from __future__ import annotations

import logging
import os

from agent.data_collector import APP_BASE_URL

logger = logging.getLogger(__name__)

# ── 임계 (env 조정 가능) ─────────────────────────────────────────
DROP_WATCH = float(os.getenv("GAP_DROP_WATCH", "-1.2"))   # 관심
DROP_CAUT  = float(os.getenv("GAP_DROP_CAUTION", "-2.0"))  # 주의
DROP_ALERT = float(os.getenv("GAP_DROP_ALERT", "-3.0"))   # 경계
VIX_WATCH  = float(os.getenv("GAP_VIX_WATCH", "24"))
VIX_CAUT   = float(os.getenv("GAP_VIX_CAUTION", "30"))
VIX_ALERT  = float(os.getenv("GAP_VIX_ALERT", "38"))
MIN_STARS  = int(os.getenv("GAP_ALERT_MIN_STARS", "1"))    # 이 등급(★ 수) 이상에서 발송
ARM_STARS  = int(os.getenv("GAP_ARM_STARS", "2"))          # 이 등급 이상에서 손절 자동무장

STAR_NAME = {1: "관심", 2: "주의", 3: "경계"}
STAR_MARK = {1: "★", 2: "★★", 3: "★★★"}


def _futures_overnight() -> tuple[float | None, float | None]:
    """나스닥·S&P 지수선물 야간 등락(%). 전일 종가 대비 최신가. 실패 시 (None, None)."""
    try:
        import yfinance as yf
        out: dict = {}
        for sym, key in (("NQ=F", "nq"), ("ES=F", "es")):
            try:
                raw = yf.Ticker(sym).history(period="5d", auto_adjust=False)
                c = raw["Close"].dropna()
                if len(c) >= 2 and c.iloc[-2]:
                    out[key] = float((c.iloc[-1] - c.iloc[-2]) / abs(c.iloc[-2]) * 100)
            except Exception:
                pass
        return out.get("nq"), out.get("es")
    except Exception:
        return None, None


def _grade(drop: float, vix: float) -> int:
    """가장 큰 낙폭(%) 과 VIX 로 위험 등급(0~3) 산출."""
    if drop <= DROP_ALERT or vix >= VIX_ALERT:
        return 3
    if drop <= DROP_CAUT or vix >= VIX_CAUT:
        return 2
    if drop <= DROP_WATCH or vix >= VIX_WATCH:
        return 1
    return 0


def _arm_stops() -> int:
    """보유종목 손절가 자동 등록/점검(무발송). 반환: 변경 건수."""
    try:
        from agent.auto_stop_alert import run as _run_stop
        r = _run_stop(send_kakao=False)
        return int(r.get("created", 0)) + int(r.get("updated", 0))
    except Exception as e:
        logger.warning(f"[gap_risk] 손절 자동등록 실패: {e}")
        return 0


def assess() -> dict:
    """간밤 신호 수집 + 등급 산출. 발송 없이 순수 평가."""
    nasdaq = sp500 = vix = None
    try:
        from XGBoost_v2.global_features import get_global_features
        g = get_global_features() or {}
        nasdaq = (g.get("nasdaq_ret_1d") or 0.0) * 100
        sp500  = (g.get("sp500_ret_1d") or 0.0) * 100
        vix    = float(g.get("vix_level") or 0.0)
    except Exception as e:
        logger.warning(f"[gap_risk] 글로벌 피처 조회 실패: {e}")

    nq, es = _futures_overnight()

    drops = [d for d in (nasdaq, sp500, nq, es) if d is not None]
    if not drops or (vix in (None, 0.0) and not drops):
        return {"ok": False, "reason": "no_data"}

    worst = min(drops) if drops else 0.0
    stars = _grade(worst, vix or 0.0)
    return {
        "ok": True, "stars": stars, "worst_drop": worst,
        "nasdaq": nasdaq, "sp500": sp500, "nq": nq, "es": es, "vix": vix,
    }


def _build_msg(a: dict, armed: int) -> str:
    stars = a["stars"]
    head = f"🌐 [{STAR_NAME[stars]} {STAR_MARK[stars]}] 장전 갭하락 위험"
    parts = []
    if a.get("nasdaq") is not None: parts.append(f"나스닥 {a['nasdaq']:+.2f}%")
    if a.get("sp500")  is not None: parts.append(f"S&P {a['sp500']:+.2f}%")
    if a.get("nq")     is not None: parts.append(f"선물 NQ {a['nq']:+.2f}%")
    if a.get("es")     is not None: parts.append(f"ES {a['es']:+.2f}%")
    if a.get("vix"):                parts.append(f"VIX {a['vix']:.1f}")
    lines = [head, "간밤: " + " · ".join(parts),
             f"→ 오늘 코스피 갭하락 가능성 '{STAR_NAME[stars]}'. 보유 비중·손절가를 점검하세요."]
    if armed:
        lines.append(f"🛡 손절가 자동 점검·등록 {armed}건 완료(개장 후 도달 시 알림).")
    return "\n".join(lines)[:1000]


def run(send_kakao: bool = True) -> dict:
    a = assess()
    if not a.get("ok"):
        logger.info(f"[gap_risk] 평가 불가: {a.get('reason')}")
        return {"ok": True, "skipped": a.get("reason")}

    stars = a["stars"]
    logger.info(f"[gap_risk] 등급 {stars}({STAR_NAME.get(stars,'정상')}), "
                f"최대낙폭 {a['worst_drop']:+.2f}%, VIX {a.get('vix')}")

    armed = _arm_stops() if stars >= ARM_STARS else 0

    if stars >= MIN_STARS and send_kakao:
        try:
            from notify.send import send_message_to_self
            send_message_to_self(_build_msg(a, armed),
                                 link_url=f"{APP_BASE_URL}/price_alert", ai_generated=True)
            logger.info(f"[gap_risk] 갭하락 경보 발송 (★{stars}, armed={armed})")
        except Exception as e:
            logger.warning(f"[gap_risk] 발송 실패: {e}")

    return {"ok": True, "stars": stars, "worst_drop": round(a["worst_drop"], 2),
            "vix": a.get("vix"), "armed": armed}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run(send_kakao="--send" in sys.argv))
