"""
bot/price_monitor.py
====================
보유 종목 실시간 가격 감시 + 조건부 알림.

기능:
  1. 목표가/손절가 알림  — 보유 종목 기준
  2. Price Alert        — alert_config.json 에 설정한 가격 도달 시
  3. Volume Spike       — 당일 거래량 20일 평균 3배 초과 시
  4. 급등/급락          — 당일 등락률 ±5% 이상 시

실행:
  .venv64\Scripts\python bot\price_monitor.py
  start_monitor.bat
"""

import os, sys, json, logging, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

KIWOOM_URL      = f"http://127.0.0.1:{os.getenv('KIWOOM_COLLECTOR_PORT', '5100')}"
RECOMMEND_JSON  = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "daily_recommend.json"
ALERT_CONFIG    = Path(__file__).parent / "alert_config.json"
OHLCV_DIR       = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ohlcv"

CHECK_INTERVAL  = 60
MARKET_OPEN     = (9,  0)
MARKET_CLOSE    = (15, 30)
VOLUME_SPIKE_X  = 3.0   # 20일 평균 거래량의 N배 초과 시 알림
SUDDEN_MOVE_PCT = 5.0   # 등락률 ±N% 이상 시 알림

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_alerted: set = set()           # (code, event_type) — 세션 내 중복 알림 방지
_pnl_reported_today: object = None  # 장마감 P&L 요약 중복 방지


# ─────────────────────────────────────────────────────────
# 시간 유틸
# ─────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


# ─────────────────────────────────────────────────────────
# Kiwoom 데이터 조회
# ─────────────────────────────────────────────────────────

def _get_holdings() -> list:
    try:
        r = requests.get(f"{KIWOOM_URL}/account/holdings", timeout=5)
        return r.json().get("holdings", [])
    except Exception as e:
        logger.debug(f"보유 조회 실패: {e}")
        return []


def _get_price_data(code: str) -> dict:
    """현재가 + 등락률 + 거래량 반환."""
    try:
        r = requests.get(f"{KIWOOM_URL}/price/{code}", timeout=5)
        return r.json()
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────
# 보조 데이터
# ─────────────────────────────────────────────────────────

def _get_avg_volume_20d(code: str) -> float:
    """OHLCV 파일에서 20일 평균 거래량 계산."""
    try:
        import pandas as pd
        path = OHLCV_DIR / f"{code}.parquet"
        if not path.exists():
            return 0.0
        df = pd.read_parquet(path)
        return float(df["volume"].tail(20).mean())
    except Exception:
        return 0.0


def _get_recommend_levels(code: str) -> dict | None:
    if not RECOMMEND_JSON.exists():
        return None
    try:
        data = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
        for cat in ("daily", "short", "swing"):
            for pick in data.get(cat, []):
                if pick.get("code") == code:
                    return {"target": pick["target"], "stop": pick["stop"]}
    except Exception:
        pass
    return None


def _load_alert_config() -> list:
    try:
        if ALERT_CONFIG.exists():
            data = json.loads(ALERT_CONFIG.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────
# 알림 발송
# ─────────────────────────────────────────────────────────

def _send(text: str):
    try:
        from notify.send import send_message_to_self
        ok = send_message_to_self(text)
        if ok:
            logger.info("[알림] 카카오톡 발송 완료")
        else:
            logger.warning("[알림] 카카오톡 발송 실패 (토큰 확인 필요)")
    except Exception as e:
        logger.error(f"[알림] 발송 실패: {e}")


# ─────────────────────────────────────────────────────────
# 1. 목표가 / 손절가 알림 (보유 종목)
# ─────────────────────────────────────────────────────────

def _check_holdings():
    holdings = _get_holdings()
    if not holdings:
        logger.info("보유 종목 없음 또는 Kiwoom 미연결")
        return

    for h in holdings:
        code      = h.get("code", "").lstrip("A")
        name      = h.get("name", code)
        avg_price = float(h.get("avg_price", 0) or 0)
        quantity  = int(h.get("quantity", 0) or 0)
        if not code or avg_price <= 0 or quantity <= 0:
            continue

        d     = _get_price_data(code)
        price = d.get("current_price") or d.get("price")
        if not price:
            continue

        rec    = _get_recommend_levels(code)
        target = rec["target"] if rec else int(avg_price * 1.05)
        stop   = rec["stop"]   if rec else int(avg_price * 0.97)
        ret    = (price - avg_price) / avg_price * 100

        logger.info(f"  {name}({code}) {price:,}원 | 목표 {target:,} | 손절 {stop:,} | {ret:+.1f}%")

        if price >= target and (code, "target") not in _alerted:
            _alerted.add((code, "target"))
            _send(f"🎯 목표가 도달!\n{name}({code})\n현재 {price:,}원 ({ret:+.1f}%)\n목표가 {target:,}원 달성 → 매도 검토")

        elif price <= stop and (code, "stop") not in _alerted:
            _alerted.add((code, "stop"))
            _send(f"🚨 손절가 도달!\n{name}({code})\n현재 {price:,}원 ({ret:+.1f}%)\n손절가 {stop:,}원 하회 → 즉시 매도 검토")


# ─────────────────────────────────────────────────────────
# 2. Price Alert (alert_config.json 기반)
# ─────────────────────────────────────────────────────────

def _check_price_alerts():
    alerts = _load_alert_config()
    for a in alerts:
        if not isinstance(a, dict):
            continue
        code      = a.get("code", "").lstrip("A")
        name      = a.get("name", code)
        threshold = int(a.get("price", 0))
        direction = a.get("direction", "above")  # "above" | "below"
        note      = a.get("note", "")
        if not code or not threshold:
            continue

        d     = _get_price_data(code)
        price = d.get("current_price") or d.get("price")
        if not price:
            continue

        key = (code, f"alert_{direction}_{threshold}")
        triggered = (direction == "above" and price >= threshold) or \
                    (direction == "below" and price <= threshold)

        if triggered and key not in _alerted:
            _alerted.add(key)
            arrow = "↑" if direction == "above" else "↓"
            _send(
                f"🔔 Price Alert!\n{name}({code})\n"
                f"현재 {price:,}원 {arrow} 설정가 {threshold:,}원\n"
                + (f"메모: {note}" if note else "")
            )


# ─────────────────────────────────────────────────────────
# 3. Volume Spike + 급등/급락 (보유 종목 + alert_config 종목)
# ─────────────────────────────────────────────────────────

def _check_volume_and_move():
    # 감시 대상: 보유 종목 + alert_config 종목
    watch = {}
    for h in _get_holdings():
        code = h.get("code", "").lstrip("A")
        if code:
            watch[code] = h.get("name", code)
    for a in _load_alert_config():
        if not isinstance(a, dict):
            continue
        code = a.get("code", "").lstrip("A")
        if code:
            watch[code] = a.get("name", code)

    for code, name in watch.items():
        d         = _get_price_data(code)
        price     = d.get("current_price") or d.get("price")
        volume    = d.get("volume") or d.get("trading_volume", 0)
        change_rt = d.get("change_rate", 0)  # 등락률 (%)
        if not price:
            continue

        # Volume Spike
        avg_vol = _get_avg_volume_20d(code)
        if avg_vol > 0 and volume and volume > avg_vol * VOLUME_SPIKE_X:
            key = (code, "vol_spike")
            if key not in _alerted:
                _alerted.add(key)
                ratio = volume / avg_vol
                _send(
                    f"📈 거래량 급증!\n{name}({code})\n"
                    f"현재 거래량 {volume:,} (평균 대비 {ratio:.1f}배)\n"
                    f"현재가 {price:,}원"
                )

        # 급등/급락
        if abs(change_rt) >= SUDDEN_MOVE_PCT:
            direction = "급등" if change_rt > 0 else "급락"
            key = (code, f"move_{direction}")
            if key not in _alerted:
                _alerted.add(key)
                emoji = "🚀" if change_rt > 0 else "📉"
                _send(
                    f"{emoji} {direction} 감지!\n{name}({code})\n"
                    f"등락률 {change_rt:+.1f}%\n현재가 {price:,}원"
                )


# ─────────────────────────────────────────────────────────
# 4. 기술적 신호 알림 (RSI / MA이격도 / 골든·데드크로스 / 볼린저밴드 / 공매도)
# ─────────────────────────────────────────────────────────

def _compute_technicals(code: str) -> dict:
    """OHLCV parquet에서 기술 지표 계산. 파일 없으면 빈 dict."""
    try:
        import numpy as np
        import pandas as pd

        path = OHLCV_DIR / f"{code}.parquet"
        if not path.exists():
            return {}
        df = pd.read_parquet(path)
        if len(df) < 30:
            return {}

        c = df["close"]
        current = float(c.iloc[-1])

        # RSI(14) — EWM 방식
        delta = c.diff()
        gain  = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss  = (-delta).clip(lower=0).ewm(com=13, min_periods=14).mean()
        rsi   = float(100 - 100 / (1 + gain.iloc[-1] / (loss.iloc[-1] + 1e-9)))

        # MA5 / MA20 (당일 + 전일)
        ma5_s   = c.rolling(5).mean()
        ma20_s  = c.rolling(20).mean()
        ma5     = float(ma5_s.iloc[-1])  if len(c) >= 5  else None
        ma20    = float(ma20_s.iloc[-1]) if len(c) >= 20 else None
        ma5_p   = float(ma5_s.iloc[-2])  if len(c) >= 6  else None
        ma20_p  = float(ma20_s.iloc[-2]) if len(c) >= 21 else None

        ma5_dev = round((current - ma5) / ma5 * 100, 2) if ma5 else None

        golden = bool(ma5 and ma20 and ma5_p and ma20_p and ma5 > ma20 and ma5_p <= ma20_p)
        dead   = bool(ma5 and ma20 and ma5_p and ma20_p and ma5 < ma20 and ma5_p >= ma20_p)

        # 볼린저밴드(20)
        std20  = float(c.rolling(20).std().iloc[-1]) if len(c) >= 20 else None
        bb_up  = ma20 + 2 * std20 if ma20 and std20 else None
        bb_dn  = ma20 - 2 * std20 if ma20 and std20 else None
        bb_pct = round((current - bb_dn) / (bb_up - bb_dn) * 100, 1) \
                 if bb_up and bb_dn and bb_up != bb_dn else None

        return {
            "price":        round(current, 0),
            "rsi":          round(rsi, 1),
            "ma5_dev":      ma5_dev,
            "golden_cross": golden,
            "dead_cross":   dead,
            "bb_pct":       bb_pct,
        }
    except Exception as e:
        logger.debug(f"[technical] {code}: {e}")
        return {}


RSI_OVERBOUGHT  = 75
RSI_OVERSOLD    = 25
MA5_DEV_HEAT    = 15.0   # MA5 이격도 과열 임계값 (%)
BB_UPPER_PCT    = 95     # 볼린저 상단 위험
BB_LOWER_PCT    = 5      # 볼린저 하단 과매도
SHORT_BAL_WARN  = 3.0    # 공매도 잔고비율 경고 임계값 (%)


def _check_technical_signals():
    """RSI·이격도·크로스·볼린저·공매도 조건 감시."""
    watch: dict[str, str] = {}
    for h in _get_holdings():
        code = h.get("code", "").lstrip("A")
        if code:
            watch[code] = h.get("name", code)
    for a in _load_alert_config():
        if isinstance(a, dict):
            code = a.get("code", "").lstrip("A")
            if code:
                watch[code] = a.get("name", code)

    for code, name in watch.items():
        t     = _compute_technicals(code)
        price = t.get("price") or 0
        rsi   = t.get("rsi")
        dev   = t.get("ma5_dev")
        bpct  = t.get("bb_pct")

        # RSI 과매수
        if rsi and rsi >= RSI_OVERBOUGHT:
            key = (code, f"rsi_ob_{int(rsi) // 5}")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"⚠ RSI 과매수!\n{name}({code})\nRSI {rsi:.1f} (기준 {RSI_OVERBOUGHT}↑)\n"
                      f"현재가 {price:,}원 — 단기 조정 위험")

        # RSI 과매도
        elif rsi and rsi <= RSI_OVERSOLD:
            key = (code, f"rsi_os_{int(rsi) // 5}")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"🔍 RSI 과매도!\n{name}({code})\nRSI {rsi:.1f} (기준 {RSI_OVERSOLD}↓)\n"
                      f"현재가 {price:,}원 — 반등 구간 진입")

        # MA5 이격도 과열
        if dev and dev >= MA5_DEV_HEAT:
            key = (code, f"dev_heat_{int(dev) // 5}")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"🔥 MA5 이격도 과열!\n{name}({code})\n이격도 {dev:+.1f}% (기준 +{MA5_DEV_HEAT}%↑)\n"
                      f"현재가 {price:,}원 — 단기 조정 가능성")

        # 골든크로스
        if t.get("golden_cross"):
            key = (code, "golden_cross")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"📈 골든크로스!\n{name}({code})\nMA5↑MA20 — 매수 신호\n현재가 {price:,}원")

        # 데드크로스
        if t.get("dead_cross"):
            key = (code, "dead_cross")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"📉 데드크로스!\n{name}({code})\nMA5↓MA20 — 매도 신호\n현재가 {price:,}원")

        # 볼린저 상단 돌파
        if bpct is not None and bpct >= BB_UPPER_PCT:
            key = (code, "bb_upper")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"⚡ 볼린저 상단 돌파!\n{name}({code})\nBB위치 {bpct:.0f}% — 과열 주의\n현재가 {price:,}원")

        # 볼린저 하단 이탈
        elif bpct is not None and bpct <= BB_LOWER_PCT:
            key = (code, "bb_lower")
            if key not in _alerted:
                _alerted.add(key)
                _send(f"❄ 볼린저 하단 이탈!\n{name}({code})\nBB위치 {bpct:.0f}% — 과매도 구간\n현재가 {price:,}원")

        # 공매도 잔고비율 급증
        try:
            from XGBoost_v2.short_features import get_short_features
            sf  = get_short_features(code)
            bal = sf.get("short_balance_pct", 0)
            if bal >= SHORT_BAL_WARN:
                key = (code, f"short_{int(bal)}")
                if key not in _alerted:
                    _alerted.add(key)
                    _send(f"⚠ 공매도 잔고 증가!\n{name}({code})\n잔고비율 {bal:.2f}% (기준 {SHORT_BAL_WARN}%↑)\n"
                          f"현재가 {price:,}원 — 하락 압력 주의")
        except Exception:
            pass

        if t:
            logger.info(f"  {name}({code}) RSI={rsi} dev={dev} BB={bpct}%")


# ─────────────────────────────────────────────────────────
# 5. 장마감 P&L 요약 (하루 1회 15:30~15:45)
# ─────────────────────────────────────────────────────────

def _check_closing_pnl():
    """보유 종목 일별 손익 합산 카톡 발송."""
    global _pnl_reported_today
    today = datetime.now().date()
    if _pnl_reported_today == today:
        return

    holdings = _get_holdings()
    if not holdings:
        return

    lines      = [f"📊 [{datetime.now().strftime('%m/%d')}] 장마감 P&L\n━━━━━━━━━━━━━━"]
    total_pnl  = 0
    has_data   = False

    for h in holdings:
        code = h.get("code", "").lstrip("A")
        name = h.get("name", code)
        avg  = float(h.get("avg_price", 0) or 0)
        qty  = int(h.get("quantity",   0) or 0)
        if not code or avg <= 0 or qty <= 0:
            continue

        d     = _get_price_data(code)
        price = d.get("current_price") or d.get("price")
        if not price:
            continue

        pnl_pct = (price - avg) / avg * 100
        pnl_amt = (price - avg) * qty
        total_pnl += pnl_amt
        has_data   = True
        emoji      = "📈" if pnl_amt >= 0 else "📉"
        lines.append(f"{emoji} {name}: {pnl_pct:+.1f}% ({pnl_amt:+,}원)")

    if has_data:
        lines.append(f"━━━━━━━━━━━━━━\n합계: {total_pnl:+,}원")
        _send("\n".join(lines))
        _pnl_reported_today = today
        logger.info(f"[마감P&L] 발송 완료 합계={total_pnl:+,}원")


# ─────────────────────────────────────────────────────────
# Kiwoom 로그인 대기
# ─────────────────────────────────────────────────────────

def _wait_for_kiwoom_login(poll_interval: int = 10):
    logger.info("Kiwoom 로그인 대기 중...")
    while True:
        try:
            r = requests.get(f"{KIWOOM_URL}/status", timeout=3)
            if r.json().get("connected"):
                logger.info("Kiwoom 로그인 확인 — 모니터링 시작")
                return
        except Exception:
            pass
        logger.info(f"  미연결, {poll_interval}초 후 재확인...")
        time.sleep(poll_interval)


# ─────────────────────────────────────────────────────────
# 메인 루프
# ─────────────────────────────────────────────────────────

def run():
    logger.info("=" * 45)
    logger.info("  가격 모니터링 시작")
    logger.info(f"  체크 주기    : {CHECK_INTERVAL}초")
    logger.info(f"  거래량 급증  : 20일 평균 {VOLUME_SPIKE_X}배 초과")
    logger.info(f"  급등/급락    : 등락률 ±{SUDDEN_MOVE_PCT}% 이상")
    logger.info("=" * 45)

    _wait_for_kiwoom_login()

    while True:
        now = datetime.now()
        if _is_market_open():
            logger.info(f"[체크] {now.strftime('%H:%M:%S')}")
            _check_holdings()
            _check_price_alerts()
            _check_volume_and_move()
            _check_technical_signals()
        else:
            logger.info(f"[대기] {now.strftime('%H:%M')} — 장 마감 또는 주말")

        # 장마감 P&L 요약 (15:30 ~ 15:45, 평일)
        if now.weekday() < 5 and (15, 30) <= (now.hour, now.minute) <= (15, 45):
            _check_closing_pnl()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"모니터링 비정상 종료: {e}", exc_info=True)
        try:
            from notify.send import notify_error
            notify_error("price_monitor", str(e))
        except Exception:
            pass
        raise
