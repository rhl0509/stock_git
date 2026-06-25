"""
XGBoost_v2/backtest_v2.py
==========================
추천 이력(model/recommend_history/*.json) 기반 백테스팅.

동작:
  1. recommend_history/ 에 저장된 과거 추천 JSON 로드
  2. 각 추천 종목의 OHLCV(로컬 parquet)로 실제 N일 수익률 계산
  3. 카테고리별 정밀도·평균수익·손실회피율 등 지표 출력

실행:
  python -m XGBoost_v2.backtest_v2
  python -m XGBoost_v2.backtest_v2 --min-conf 0.60 --output report.json
"""
from __future__ import annotations

import json, logging, argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT        = Path(__file__).parent
MODEL_DIR   = ROOT / 'model'
HISTORY_DIR = MODEL_DIR / 'recommend_history'

HOLD_DAYS = {"daily": 3, "short": 5, "swing": 14}


# ─────────────────────────────────────────────────────────────────────────
# 수익률 계산
# ─────────────────────────────────────────────────────────────────────────

def _actual_return(ohlcv: pd.DataFrame, entry_date: str,
                   hold_days: int) -> Optional[dict]:
    """
    entry_date 다음 영업일 시가 진입 → hold_days 후 종가 청산 기준 수익률.

    반환: {ret, max_dd, hit(bool)} 또는 None (데이터 부족)
    """
    try:
        # entry_date 이후 첫 거래일
        entry_ts = pd.Timestamp(entry_date)
        future   = ohlcv[ohlcv.index > entry_ts]
        if len(future) < 2:
            return None

        buy_price = float(future["open"].iloc[0])   # 진입가: 다음날 시가
        if buy_price <= 0:
            return None

        period = future.iloc[:hold_days]
        if len(period) < 1:
            return None

        sell_price = float(period["close"].iloc[-1])
        ret        = (sell_price - buy_price) / buy_price
        max_dd     = float((period["low"].min() - buy_price) / buy_price)
        return {"ret": ret, "max_dd": max_dd, "hit": ret > 0}
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────
# 단일 히스토리 파일 평가
# ─────────────────────────────────────────────────────────────────────────

def _eval_history_file(path: Path, min_conf: float = 0.0) -> list[dict]:
    """추천 JSON 1개를 평가하여 결과 행 리스트 반환."""
    from .collect_v2 import load_ohlcv

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return []

    base_date = data.get("base_date", "")
    if not base_date:
        return []

    rows = []
    for category, items in [("daily",  data.get("daily",  [])),
                             ("short",  data.get("short",  [])),
                             ("swing",  data.get("swing",  []))]:
        hold = HOLD_DAYS[category]
        for item in items:
            conf = float(item.get("confidence", 0))
            if conf < min_conf:
                continue
            code  = item.get("code", "")
            ohlcv = load_ohlcv(code)
            if ohlcv is None:
                continue
            result = _actual_return(ohlcv, base_date, hold)
            if result is None:
                continue
            rows.append({
                "date":       base_date,
                "code":       code,
                "name":       item.get("name", code),
                "category":   category,
                "confidence": conf,
                "source":     item.get("source", "?"),
                "ret":        result["ret"],
                "max_dd":     result["max_dd"],
                "hit":        result["hit"],
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────
# 성과 지표 집계
# ─────────────────────────────────────────────────────────────────────────

def _aggregate(rows: list[dict]) -> dict:
    """전체 / 카테고리별 / 소스별 성과 집계."""
    if not rows:
        return {"error": "평가 가능한 결과 없음"}

    df = pd.DataFrame(rows)

    def _metrics(sub: pd.DataFrame) -> dict:
        if sub.empty:
            return {}
        rets  = sub["ret"].values
        hits  = sub["hit"].values
        dds   = sub["max_dd"].values
        return {
            "n_picks":        int(len(sub)),
            "hit_rate":       round(float(hits.mean()), 4),
            "avg_ret":        round(float(rets.mean()), 4),
            "median_ret":     round(float(np.median(rets)), 4),
            "avg_win":        round(float(rets[rets > 0].mean()) if any(rets > 0) else 0, 4),
            "avg_loss":       round(float(rets[rets < 0].mean()) if any(rets < 0) else 0, 4),
            "avg_max_dd":     round(float(dds.mean()), 4),
            "sharpe_approx":  round(float(rets.mean() / (rets.std() + 1e-9)), 4),
            "profit_factor":  round(
                float(rets[rets > 0].sum() / (-rets[rets < 0].sum() + 1e-9)), 4),
        }

    report = {
        "evaluated_at":    datetime.now().isoformat(),
        "n_history_files": int(df["date"].nunique()),
        "overall":         _metrics(df),
        "by_category": {
            cat: _metrics(df[df["category"] == cat])
            for cat in ["daily", "short", "swing"]
        },
        "by_source": {
            src: _metrics(df[df["source"] == src])
            for src in df["source"].unique()
        },
        "by_confidence_bucket": {},
    }

    # 신뢰도 구간별
    for lo, hi in [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01)]:
        bucket = df[(df["confidence"] >= lo) & (df["confidence"] < hi)]
        key    = f"{lo:.2f}-{hi:.2f}"
        report["by_confidence_bucket"][key] = _metrics(bucket)

    return report


# ─────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────

def run_backtest(min_conf: float = 0.0,
                 days_back: int = 90,
                 output_path: Optional[str] = None) -> dict:
    """
    백테스트 실행.

    Args:
        min_conf:    최소 신뢰도 필터 (0.0 = 전체)
        days_back:   최근 N일 히스토리만 사용
        output_path: 결과 JSON 저장 경로 (None = 저장 안 함)
    """
    if not HISTORY_DIR.exists():
        return {"error": f"{HISTORY_DIR} 없음. daily_recommend를 먼저 실행하세요."}

    def _parse_stem(stem: str) -> datetime | None:
        for fmt in ["%Y%m%d", "%Y-%m-%d"]:
            try:
                return datetime.strptime(stem, fmt)
            except ValueError:
                continue
        return None

    cutoff   = datetime.now() - timedelta(days=days_back)
    today    = datetime.now().date()
    files    = sorted(HISTORY_DIR.glob("*.json"))
    files    = [f for f in files
                if (d := _parse_stem(f.stem)) is not None
                and d >= cutoff
                and d.date() != today]

    if not files:
        return {"error": f"최근 {days_back}일 내 히스토리 파일 없음"}

    logger.info(f"[backtest] 파일 {len(files)}개 평가 중 (min_conf={min_conf})")

    all_rows = []
    for f in files:
        rows = _eval_history_file(f, min_conf=min_conf)
        all_rows.extend(rows)
        logger.info(f"  {f.stem}: {len(rows)}개 유효 결과")

    report = _aggregate(all_rows)
    report["settings"] = {
        "min_conf":  min_conf,
        "days_back": days_back,
        "n_files":   len(files),
    }

    if output_path:
        Path(output_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f"[backtest] 결과 저장: {output_path}")

    return report


def _print_report(report: dict) -> None:
    """콘솔 출력용 요약."""
    if "error" in report:
        print(f"[ERROR] {report['error']}")
        return

    ov = report.get("overall", {})
    print("\n" + "=" * 55)
    print(f"  백테스트 결과  ({report.get('n_history_files',0)}일)")
    print("=" * 55)
    print(f"  전체 신호    : {ov.get('n_picks', 0):,}개")
    print(f"  적중률       : {ov.get('hit_rate', 0):.1%}")
    print(f"  평균 수익률  : {ov.get('avg_ret', 0):+.2%}")
    print(f"  평균 낙폭    : {ov.get('avg_max_dd', 0):.2%}")
    print(f"  Profit Factor: {ov.get('profit_factor', 0):.2f}")
    print()
    print(f"  {'카테고리':<8} {'건수':>5} {'적중률':>8} {'평균수익':>9}")
    print(f"  {'-'*36}")
    for cat in ["daily", "short", "swing"]:
        m = report["by_category"].get(cat, {})
        print(f"  {cat:<8} {m.get('n_picks',0):>5} "
              f"{m.get('hit_rate',0):>7.1%}  "
              f"{m.get('avg_ret',0):>+8.2%}")
    print()
    print(f"  신뢰도 구간별:")
    for bucket, m in report.get("by_confidence_bucket", {}).items():
        if m.get("n_picks", 0) > 0:
            print(f"  [{bucket}]  n={m['n_picks']:>4}  "
                  f"적중 {m.get('hit_rate',0):.1%}  "
                  f"평균수익 {m.get('avg_ret',0):+.2%}")
    print()
    # 모델 vs 팩터
    for src, m in report.get("by_source", {}).items():
        if m.get("n_picks", 0) > 0:
            print(f"  [{src:6}]  n={m['n_picks']:>4}  "
                  f"적중 {m.get('hit_rate',0):.1%}  "
                  f"평균수익 {m.get('avg_ret',0):+.2%}")
    print("=" * 55)


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="종목 추천 백테스트")
    parser.add_argument('--min-conf', type=float, default=0.0,
                        help='최소 신뢰도 필터 (기본 0 = 전체)')
    parser.add_argument('--days-back', type=int, default=90,
                        help='최근 N일 히스토리 사용 (기본 90)')
    parser.add_argument('--output', default=None,
                        help='결과 JSON 저장 경로')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    report = run_backtest(min_conf=args.min_conf,
                          days_back=args.days_back,
                          output_path=args.output)
    _print_report(report)
