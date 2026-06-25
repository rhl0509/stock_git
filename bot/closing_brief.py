"""
bot/closing_brief.py
====================
장 마감 브리핑 — 오늘 추천 종목 수익률을 카카오톡으로 발송.

실행:
  .venv64\Scripts\python bot\closing_brief.py
  (작업 스케줄러: 매일 15:35)
"""
import sys, json, logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

from config import Config
KIWOOM_URL = f"http://127.0.0.1:{Config.KIWOOM_COLLECTOR_PORT}"
RECOMMEND_JSON = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "daily_recommend.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _get_price(code: str) -> int | None:
    # 1차: 키움 32bit 서버
    try:
        r = requests.get(f"{KIWOOM_URL}/price/{code}", timeout=3)
        d = r.json()
        p = d.get("current_price") or d.get("price")
        if p:
            return int(p)
    except Exception:
        pass
    # 2차 폴백: 네이버 금융 모바일 API
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/basic",
            timeout=5, headers={"User-Agent": "Mozilla/5.0"}
        )
        p = r.json().get("closePrice", "")
        if p:
            return int(str(p).replace(",", ""))
    except Exception:
        pass
    return None


def build_closing_message(data: dict) -> str:
    today = datetime.now().strftime("%m월 %d일")
    hit_target, hit_stop, neutral = [], [], []

    for cat in ("daily", "short", "swing"):
        for p in data.get(cat, [])[:5]:
            code  = p.get("code", "")
            name  = p.get("name", code)
            entry = int(p.get("price", 0))
            tgt   = int(p.get("target", 0))
            stp   = int(p.get("stop", 0))

            price = _get_price(code)
            if not price or not entry:
                continue

            ret = (price - entry) / entry * 100
            line = f"{name}({code}) {ret:+.1f}% | 현재 {price:,}"

            if price >= tgt:
                hit_target.append("🎯 " + line)
            elif price <= stp:
                hit_stop.append("🚨 " + line)
            else:
                neutral.append("📌 " + line)

    lines = [f"📊 [{today}] 장 마감 브리핑", "━" * 18]

    if hit_target:
        lines += ["", "✅ 목표가 도달"] + hit_target
    if hit_stop:
        lines += ["", "⚠ 손절가 하회"] + hit_stop
    if neutral:
        lines += ["", "진행 중"] + neutral[:5]

    total = len(hit_target) + len(hit_stop) + len(neutral)
    lines += [
        "", "━" * 18,
        f"목표달성 {len(hit_target)}개 | 손절 {len(hit_stop)}개 | 보유 {len(neutral)}개 / 총 {total}개",
    ]
    return "\n".join(lines)


def send_closing_brief() -> bool:
    if not RECOMMEND_JSON.exists():
        logger.error("daily_recommend.json 없음")
        return False

    data = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
    msg  = build_closing_message(data)
    logger.info("\n" + msg)

    try:
        from notify.send import send_message_to_self
        return send_message_to_self(msg)
    except Exception as e:
        logger.error(f"카카오톡 발송 실패: {e}")
        return False


if __name__ == "__main__":
    sys.exit(0 if send_closing_brief() else 1)
