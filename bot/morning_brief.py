"""
bot/morning_brief.py
====================
장 시작 전 아침 브리핑 — 오늘의 추천 종목 + 거시지표 카카오톡 발송.

실행:
  .venv64\Scripts\python bot\morning_brief.py
  (작업 스케줄러: 매일 08:50)
"""
import os, sys, json, logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

RECOMMEND_JSON = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "daily_recommend.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _macro_summary() -> str:
    try:
        from XGBoost_v2.bok_client import get_macro_features
        from XGBoost_v2.global_features import get_global_features
        m = get_macro_features()
        g = get_global_features()
        lines = []
        if m.get("usdkrw_ret_20d") is not None:
            direction = "↑" if m["usdkrw_ret_20d"] > 0 else "↓"
            lines.append(f"원/달러 {direction} ({m['usdkrw_ret_20d']*100:+.1f}%/20d)")
        if g.get("sp500_ret_1d") is not None:
            direction = "↑" if g["sp500_ret_1d"] > 0 else "↓"
            lines.append(f"S&P500 {direction} ({g['sp500_ret_1d']*100:+.2f}%/1d)")
        if g.get("vix_level"):
            lines.append(f"VIX {g['vix_level']:.1f}")
        if m.get("bond_3y"):
            lines.append(f"국고채3y {m['bond_3y']:.2f}%")
        return "  " + " | ".join(lines) if lines else ""
    except Exception:
        return ""


def build_morning_message(data: dict) -> str:
    today = datetime.now().strftime("%m월 %d일")
    base  = data.get("base_date", "")
    lines = [f"🌅 [{today}] 아침 브리핑", "━" * 18]

    macro = _macro_summary()
    if macro:
        lines += ["", "📡 거시지표", macro]

    triple = data.get("triple", [])
    if triple:
        lines += ["", "⭐ 강력추천 (3개 라벨 동시 신호)"]
        for p in triple[:3]:
            conf = int(p.get("combined_score", 0) * 100)
            lines.append(f"  • {p.get('name')}({p.get('code')}) 통합신뢰도{conf}%")

    label_map = {"daily": "🔥 데일리(3일)", "short": "📈 단타(5일)", "swing": "📊 스윙(14일)"}
    for cat, title in label_map.items():
        picks = data.get(cat, [])[:3]
        if not picks:
            continue
        lines += ["", title]
        for p in picks:
            conf = int(p.get("confidence", 0) * 100)
            tgt  = p.get("target", 0)
            stp  = p.get("stop", 0)
            lines.append(
                f"  • {p.get('name')}({p.get('code')}) "
                f"신뢰도{conf}% | 목표{tgt:,} | 손절{stp:,}"
            )

    n_buy = data.get("n_buy", 0)
    lines += [
        "", "━" * 18,
        f"총 매수신호 {n_buy}개 | 기준일 {base}",
        "⚠ 참고용. 투자 책임은 본인.",
    ]
    return "\n".join(lines)


def send_morning_brief() -> bool:
    if not RECOMMEND_JSON.exists():
        logger.error("daily_recommend.json 없음 — daily_recommend 먼저 실행 필요")
        return False

    data = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
    msg  = build_morning_message(data)
    logger.info("\n" + msg)

    try:
        from notify.send import send_message_to_self
        port = int(os.getenv('FLASK_PORT', '5000'))
        return send_message_to_self(msg, link_url=f"http://localhost:{port}/stock_recommend_history")
    except Exception as e:
        logger.error(f"카카오톡 발송 실패: {e}")
        return False


if __name__ == "__main__":
    sys.exit(0 if send_morning_brief() else 1)
