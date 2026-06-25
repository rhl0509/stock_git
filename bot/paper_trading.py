"""
bot/paper_trading.py — 가상매매 기록 및 결과 추적.

흐름:
  1. daily_recommend.json 읽어서 신규 추천 → OPEN 상태로 기록
  2. OPEN 거래를 OHLCV로 체크 → HIT/STOP/TIMEOUT 자동 처리
  3. paper_trades.json 저장

실행:
  .venv64\\Scripts\\python bot\\paper_trading.py
"""
import json, logging, sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

RECOMMEND_JSON = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "daily_recommend.json"
TRADES_JSON    = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "paper_trades.json"
OHLCV_DIR      = Path(__file__).parent.parent / "XGBoost_v2" / "data" / "ohlcv"

HOLD_DAYS    = {"daily": 3, "short": 5, "swing": 14}
COMMISSION   = 0.00015   # 편도 수수료 0.015% (온라인 증권사 기준)
SLIPPAGE     = 0.001     # 슬리피지 0.1% (매수 시 상향, 매도 시 하향)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _load_trades() -> list:
    if TRADES_JSON.exists():
        try:
            return json.loads(TRADES_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_trades(trades: list) -> None:
    TRADES_JSON.write_text(json.dumps(trades, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_ohlcv(code: str) -> pd.DataFrame | None:
    p = OHLCV_DIR / f"{code}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def open_new_trades() -> int:
    """daily_recommend.json 의 추천 종목을 신규 가상매매로 등록."""
    if not RECOMMEND_JSON.exists():
        logger.warning("daily_recommend.json 없음")
        return 0

    data   = json.loads(RECOMMEND_JSON.read_text(encoding="utf-8"))
    trades = _load_trades()
    today  = datetime.now().strftime("%Y%m%d")

    existing_ids = {t["id"] for t in trades}
    opened = 0

    for cat in ("triple", "daily", "short", "swing"):
        for pick in data.get(cat, []):
            code = pick.get("code", "")
            tid  = f"{today}_{code}_{cat}"
            if tid in existing_ids:
                continue

            hold = HOLD_DAYS.get(cat, 5)
            exit_by = (datetime.now() + timedelta(days=hold + 3)).strftime("%Y%m%d")

            raw_entry = int(pick.get("entry") or pick.get("price") or 0)
            # 슬리피지 반영 실제 체결가 (매수: 호가 위로)
            actual_entry = int(raw_entry * (1 + SLIPPAGE)) if raw_entry > 0 else 0
            trades.append({
                "id":           tid,
                "code":         code,
                "name":         pick.get("name", code),
                "category":     cat,
                "entry_date":   today,
                "entry_price":  actual_entry,
                "raw_entry":    raw_entry,
                "target":       int(pick.get("target") or 0),
                "stop":         int(pick.get("stop") or 0),
                "hold_days":    hold,
                "exit_by":      exit_by,
                "confidence":   round(float(pick.get("confidence") or pick.get("combined_score") or 0), 4),
                "status":       "OPEN",
                "exit_date":    None,
                "exit_price":   None,
                "return_pct":   None,
                "net_return_pct": None,
                "commission":   round(COMMISSION * 2, 6),
                "slippage":     round(SLIPPAGE * 2, 4),
                "source":       pick.get("source", "model"),
            })
            opened += 1

    _save_trades(trades)
    logger.info(f"[paper] 신규 {opened}개 등록 | 누적 {len(trades)}개")
    return opened


def _fetch_ohlcv_pykrx(code: str, start: str, end: str) -> pd.DataFrame | None:
    """pykrx로 OHLCV 조회 — 로컬 parquet 없는 종목 폴백용."""
    try:
        from pykrx import stock as pkstock
        df = pkstock.get_market_ohlcv(start, end, code)
        if df is None or df.empty:
            return None
        df = df.rename(columns={"시가": "open", "고가": "high", "저가": "low",
                                 "종가": "close", "거래량": "volume"})
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def check_open_trades() -> dict:
    """OPEN 거래를 OHLCV로 체크해서 HIT/STOP/TIMEOUT 처리."""
    trades = _load_trades()
    today  = datetime.now().strftime("%Y%m%d")

    # pykrx 폴백용: OPEN 거래 중 가장 이른 진입일부터 오늘까지
    open_trades = [t for t in trades if t["status"] == "OPEN"]
    pykrx_start = min((t["entry_date"] for t in open_trades), default=today)

    hit, stop, timeout, still_open = 0, 0, 0, 0
    ohlcv_cache: dict = {}

    for t in trades:
        if t["status"] != "OPEN":
            continue

        code       = t["code"]
        entry      = t["entry_price"]
        target     = t["target"]
        stop_price = t["stop"]
        exit_by    = t.get("exit_by", "")

        if code not in ohlcv_cache:
            df = _load_ohlcv(code)
            if df is None:
                df = _fetch_ohlcv_pykrx(code, pykrx_start, today)
            ohlcv_cache[code] = df
        df = ohlcv_cache[code]

        if df is None or entry <= 0:
            still_open += 1
            continue

        # 진입일 이후 데이터만 확인
        entry_dt = pd.Timestamp(t["entry_date"])
        after    = df[df.index > entry_dt]

        exit_price = None
        exit_date  = None
        status     = None

        for dt, row in after.iterrows():
            h = float(row.get("high", row.get("close", 0)))
            l = float(row.get("low",  row.get("close", 0)))
            c = float(row.get("close", 0))

            if target > 0 and h >= target:
                exit_price, exit_date, status = target, dt.strftime("%Y%m%d"), "HIT"
                break
            if stop_price > 0 and l <= stop_price:
                exit_price, exit_date, status = stop_price, dt.strftime("%Y%m%d"), "STOP"
                break

        # 기간 만료
        if status is None and today >= exit_by:
            last = after.iloc[-1] if not after.empty else None
            if last is not None:
                exit_price = int(last.get("close", entry))
                exit_date  = after.index[-1].strftime("%Y%m%d")
                status     = "TIMEOUT"

        if status:
            # 매도 슬리피지 반영 실제 체결가 (매도: 호가 아래로)
            actual_exit = int(exit_price * (1 - SLIPPAGE))
            gross_ret   = (exit_price - entry) / entry * 100 if entry > 0 else 0
            cost_pct    = (COMMISSION * 2 + SLIPPAGE * 2) * 100   # 왕복 비용
            net_ret     = gross_ret - cost_pct
            t["status"]         = status
            t["exit_date"]      = exit_date
            t["exit_price"]     = int(actual_exit)
            t["return_pct"]     = round(gross_ret, 2)
            t["net_return_pct"] = round(net_ret, 2)
            if status == "HIT":    hit     += 1
            elif status == "STOP": stop    += 1
            else:                  timeout += 1
        else:
            still_open += 1

    _save_trades(trades)
    result = {"hit": hit, "stop": stop, "timeout": timeout, "open": still_open}
    logger.info(f"[paper] 체크 완료 — {result}")
    return result


def get_summary() -> dict:
    """가상매매 성과 요약."""
    trades  = _load_trades()
    closed  = [t for t in trades if t["status"] != "OPEN"]
    open_   = [t for t in trades if t["status"] == "OPEN"]

    if not closed:
        return {"n_closed": 0, "n_open": len(open_), "win_rate": 0,
                "avg_return": 0, "avg_net_return": 0,
                "total_trades": len(trades), "by_category": {}}

    rets     = [t["return_pct"]     for t in closed if t.get("return_pct")     is not None]
    net_rets = [t.get("net_return_pct", t.get("return_pct", 0)) for t in closed
                if t.get("net_return_pct") is not None or t.get("return_pct") is not None]
    wins     = [r for r in net_rets if r > 0]

    by_cat = {}
    for cat in ("triple", "daily", "short", "swing"):
        cat_closed = [t for t in closed if t["category"] == cat]
        cat_rets   = [t.get("net_return_pct", t.get("return_pct", 0))
                      for t in cat_closed if t.get("return_pct") is not None]
        cat_wins   = [r for r in cat_rets if r > 0]
        if cat_closed:
            by_cat[cat] = {
                "n":          len(cat_closed),
                "win_rate":   round(len(cat_wins) / len(cat_rets) * 100, 1) if cat_rets else 0,
                "avg_return": round(float(np.mean(cat_rets)), 2) if cat_rets else 0,
            }

    return {
        "n_closed":       len(closed),
        "n_open":         len(open_),
        "win_rate":       round(len(wins) / len(net_rets) * 100, 1) if net_rets else 0,
        "avg_return":     round(float(np.mean(rets)), 2)     if rets     else 0,
        "avg_net_return": round(float(np.mean(net_rets)), 2) if net_rets else 0,
        "total_trades":   len(trades),
        "by_category":    by_cat,
    }


def run() -> None:
    open_new_trades()
    check_open_trades()
    summary = get_summary()
    logger.info(f"[paper] 요약: 승률 {summary['win_rate']}% | "
                f"평균 {summary['avg_return']}% | 종료 {summary['n_closed']}건")


if __name__ == "__main__":
    run()
