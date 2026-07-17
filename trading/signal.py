"""
trading/signal.py
──────────────────────────────────────────────────────────────────────────────
단일 종목 매매 신호 서빙 어댑터 — XGBoost_v2 앙상블을 감싼다.

■ 배경
  이 파일에는 초기 커밋(f94673c)부터 학습 스크립트 내용이 들어가 있어, 호출자가
  기대하는 predict / get_model_status / reload_model 이 정의된 적이 없다. 그 탓에
  routes/stock_ml.py 의 XGBoost 경로와 trader.run_signal 이 ImportError 로 조용히
  죽어 있었다(양쪽 다 except 로 삼킨다). 학습 스크립트는 trading/train.py 로 옮기고,
  이 파일에는 호출자가 기대하는 서빙 API만 둔다.

■ 모델·피처
  XGBoost_v2/model/ 의 앙상블(xgb_v2_{daily,short,swing} + scaler_v2 + meta_v2_*)을 쓴다.
  trading/model/ 의 v1 아티팩트는 존재하지 않으며, trading/feature.py(34개 피처)는
  이 모델(82개 피처)과 교집합이 16개뿐이라 호환되지 않는다. 따라서 피처 빌더도
  XGBoost_v2/feature_v2.py 를 쓴다. 추론 절차는 daily_recommend._score_one 과 동일하게
  맞춰, 일별 추천과 단건 조회가 같은 값을 내도록 한다.

■ 신호 규약 (trading/trader.py 가 기대하는 형태)
  predict() → {"signal": "BUY"|"HOLD"|"ERROR", "prob_buy", "prob_sell",
               "price", "reason", ...}

  모델 출력은 "N일 내 목표수익 달성 + 낙폭 제한" 확률이다(daily=3일/+2%/-1.5%).

  [SELL 을 내지 않는 이유]
  이 모델에는 매도 라벨이 없다. P(목표 달성)의 여집합에는 하락뿐 아니라 횡보·소폭
  상승·목표 미달이 모두 섞이므로 (1 - prob_buy) 를 매도 확률로 쓰면 근거 없이
  대다수 종목이 SELL 이 된다. 따라서 BUY/HOLD 만 내고, 청산은 trader 의
  손절·익절(_check_exit_conditions — HOLD 응답 시 호출된다)에 맡긴다.
  매도 신호가 필요하면 매도 라벨을 별도로 학습해야 한다. prob_sell 은 하위 호환을
  위해 계산해 싣되 판정에는 쓰지 않는다.

■ 호출자
  routes/stock_ml.py : predict / get_model_status / reload_model
  trading/trader.py  : predict  (실주문 송신은 trader 쪽에서 영구 차단되어 있다)

■ 실행 (자가진단)
  python -m trading.signal      ← 리포지토리 루트에서. `python trading/signal.py` 는
                                   sys.path 문제로 XGBoost_v2 임포트에 실패한다.
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "XGBoost_v2" / "model"
REPORT_FILE = MODEL_DIR / "train_report_v2.json"


def _env_prob(key: str, default: float) -> float:
    """
    0~1 확률 env 파싱. 잘못된 값이면 경고 후 기본값.

    import 시점에 ValueError 를 내면 이 모듈의 import 자체가 실패하고, 호출자의
    광범위 except 가 그것을 삼켜 '조용히 죽는' 원래 상태로 돌아간다.
    """
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"[signal] {key}='{raw}' 를 실수로 읽을 수 없음 → 기본값 {default}")
        return default
    if not 0.0 < value < 1.0:
        logger.warning(f"[signal] {key}={value} 가 (0, 1) 범위 밖 → 기본값 {default}")
        return default
    return value


# 매수 임계값 — trading/trader.py RiskConfig 와 같은 env 키·기본값을 쓴다.
# (trader 를 import 하면 순환 참조가 되므로 값만 맞춘다.)
MIN_BUY_PROB: float = _env_prob("MIN_BUY_PROB", 0.60)

# build_technical 이 지표를 채우려면 필요한 최소 행수 (daily_recommend._score_one 과 동일)
MIN_OHLCV_ROWS: int = 80

PRIMARY_LABEL: str = "daily"
LABELS: tuple[str, ...] = ("daily", "short", "swing")

_OHLCV_REQUIRED: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"})

# 앙상블 Booster 는 daily_recommend 의 ThreadPoolExecutor(8) 와 FastAPI 스레드풀이
# 공유한다. xgboost/lightgbm Booster.predict 의 스레드 안전성은 보장되지 않으므로
# (버전별 동작 — 확인 필요) 이 모듈의 추론은 직렬화한다.
_predict_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _error(code: str, name: str, reason: str) -> dict[str, Any]:
    """호출자(trader.run_signal / stock_ml._predict_xgb)가 판정하는 ERROR 형태."""
    logger.warning(f"[signal] {name}({code}) → ERROR: {reason}")
    return {
        "signal": "ERROR",
        "reason": reason,
        "ticker": code,
        "ticker_name": name,
        "price": 0.0,
        "prob_buy": 0.0,
        "prob_sell": 0.0,
    }


def _normalize_code(ticker: str) -> str:
    """'005930.KS' / '005930.KQ' / '005930' → '005930'."""
    t = (ticker or "").strip().upper()
    for suffix in (".KS", ".KQ"):
        if t.endswith(suffix):
            return t[: -len(suffix)]
    return t


def _lookup_market(code: str) -> str:
    """
    kr_stocks 에서 시장 구분 조회. 실패 시 KOSPI 가정.

    DB 장애 시 KOSDAQ 종목을 KOSPI 로 평가하게 되어 build_static_features 가 다른 값을
    내고, '일별 추천과 단건 조회가 같은 값' 이라는 이 모듈의 전제가 깨진다. 그래서
    debug 가 아니라 warning 으로 남긴다.
    """
    try:
        from database.db_connection import get_db_connection

        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT market FROM kr_stocks WHERE code = %s LIMIT 1", (code,))
            row = cur.fetchone()
        finally:
            conn.close()
        if row and row.get("market"):
            return str(row["market"])
        logger.warning(f"[signal] {code} 가 kr_stocks 에 없음 → KOSPI 가정 (피처가 달라질 수 있음)")
    except Exception as e:
        logger.warning(f"[signal] {code} 시장 조회 실패 → KOSPI 가정 (피처가 달라질 수 있음): {e}")
    return "KOSPI"


def _normalize_ohlcv(df: pd.DataFrame | None) -> tuple[pd.DataFrame | None, str]:
    """
    호출자가 넘긴 OHLCV를 feature_v2.build_technical 이 받는 형태로 맞춘다.

    Returns:
        (정규화된 df, "") 또는 (None, 실패 사유). 사유를 그대로 호출자에게 전달해야
        "OHLCV 부족 — 수집 필요" 같은 틀린 처방이 나가지 않는다.
    """
    if df is None or len(df) == 0:
        return None, "OHLCV 가 비어 있음"

    out = df.copy()
    # yfinance MultiIndex 컬럼이면 str(c) 가 "('close', '005930.ks')" 가 되어 검사에서
    # 탈락한다. 첫 레벨만 취해 평탄화한다.
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]

    if not isinstance(out.index, pd.DatetimeIndex):
        for cand in ("date", "일자", "datetime"):
            if cand in out.columns:
                out = out.set_index(pd.to_datetime(out[cand], errors="coerce"))
                break
        else:
            # to_datetime(errors="coerce") 는 정수 인덱스를 NaT 로 만들지 않고 epoch
            # 나노초로 해석해 1970-01-01 대로 바꾼다. 그러면 market_df reindex 가
            # 전부 NaN → nan_to_num 이 0 으로 덮어 시장 상대강도 피처가 통째로 0 인 채
            # 그럴듯한 신호가 나간다. 숫자 인덱스는 명시적으로 거부한다.
            if pd.api.types.is_numeric_dtype(out.index):
                return None, "OHLCV 인덱스가 날짜가 아님 (숫자 인덱스 — date 컬럼 필요)"
            out.index = pd.to_datetime(out.index, errors="coerce")
        out = out[out.index.notna()]
        if len(out) == 0:
            return None, "OHLCV 인덱스를 날짜로 변환한 결과가 비어 있음"

    missing = sorted(_OHLCV_REQUIRED - set(out.columns))
    if missing:
        return None, f"OHLCV 컬럼 누락: {missing}"
    if out.columns.duplicated().any():
        dups = sorted(out.columns[out.columns.duplicated()].unique())
        return None, f"OHLCV 컬럼 중복: {dups}"
    return out.sort_index(), ""


def _load_report() -> dict[str, Any]:
    """train_report_v2.json — 학습 시점·설정 표시용(없어도 예측에는 지장 없음)."""
    if not REPORT_FILE.exists():
        return {}
    try:
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(f"[signal] 학습 리포트 읽기 실패: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────

def predict(ticker: str, ticker_name: str = "",
            ohlcv_df: pd.DataFrame | None = None) -> dict[str, Any]:
    """
    단일 종목 매매 신호.

    Args:
        ticker      : 종목코드 ('005930' 또는 '005930.KS')
        ticker_name : 종목명 (뉴스 감성 피처에 쓰임. 없으면 코드로 대체)
        ohlcv_df    : OHLCV DataFrame. None 이면 XGBoost_v2 로컬 parquet 에서 로드.

    Returns:
        {"signal": "BUY"|"SELL"|"HOLD"|"ERROR", "prob_buy", "prob_sell",
         "price", "reason", "prob_up", "prob_down", "confidence", ...}
    """
    code = _normalize_code(ticker)
    name = ticker_name or code
    if not code:
        return _error(code, name, "종목코드가 비어 있음")

    try:
        from XGBoost_v2.collect_v2 import load_ohlcv
        from XGBoost_v2.daily_recommend import _load_ensemble, _predict_ensemble
        from XGBoost_v2.feature_v2 import (build_full_matrix, build_static_features,
                                           build_technical, get_macro, get_market_ohlcv)
    except Exception as e:
        return _error(code, name, f"XGBoost_v2 모듈 임포트 실패: {e}")

    ensemble = _load_ensemble()
    if ensemble is None:
        # 경로는 로그로만 — /ml/status 는 무인증이라 응답에 절대경로를 싣지 않는다.
        logger.error(f"[signal] 앙상블 로드 실패 — 확인: {MODEL_DIR}")
        return _error(code, name, "앙상블 모델을 로드하지 못했습니다 (모델 파일 확인 필요)")

    if ohlcv_df is not None:
        ohlcv, why = _normalize_ohlcv(ohlcv_df)
        if ohlcv is None:
            return _error(code, name, why)
    else:
        ohlcv = load_ohlcv(code)
        if ohlcv is None:
            return _error(code, name,
                          "로컬 OHLCV 없음 — 수집 필요 (python -m XGBoost_v2.collect_v2)")

    if len(ohlcv) < MIN_OHLCV_ROWS:
        return _error(code, name,
                      f"OHLCV 행 부족 ({len(ohlcv)}행 < {MIN_OHLCV_ROWS}행)")

    # 공유 Booster 에 대한 동시 predict 를 직렬화한다.
    with _predict_lock:
        try:
            features = ensemble["features"]
            tech = build_technical(ohlcv, get_market_ohlcv())
            static = build_static_features(code, name, _lookup_market(code))
            X_df = build_full_matrix(tech, static, get_macro())

            # 학습 당시 피처가 빠졌으면 0으로 채워 열 순서를 모델과 맞춘다.
            for col in features:
                if col not in X_df.columns:
                    X_df[col] = 0.0

            X_latest = X_df[features].iloc[-1:].values.astype(np.float32)
            X_latest = np.nan_to_num(X_latest, nan=0.0, posinf=0.0, neginf=0.0)
            X_scaled = ensemble["scaler"].transform(X_latest)

            confs: dict[str, float] = {}
            for label in LABELS:
                if label in ensemble["labels"]:
                    confs[label] = float(_predict_ensemble(ensemble, X_scaled, label)[0])

            prob_buy = confs.get(PRIMARY_LABEL)
            if prob_buy is None:
                return _error(code, name, f"'{PRIMARY_LABEL}' 라벨 모델 없음 — 재학습 필요")

            # int() 는 종가가 NaN 이면 ValueError 를 낸다. try 안에 둬야 규약대로
            # _error dict 가 나가고, 상위 except 에 삼켜지지 않는다.
            price = int(ohlcv["close"].iloc[-1])
        except Exception as e:
            logger.error(f"[signal] {name}({code}) 예측 실패: {e}", exc_info=True)
            return _error(code, name, f"예측 실패: {e}")

    # 매도 라벨이 없으므로 BUY/HOLD 만 낸다(모듈 docstring 의 [SELL 을 내지 않는 이유]).
    # 청산은 trader 가 HOLD 응답 시 호출하는 _check_exit_conditions(손절·익절)가 맡는다.
    if prob_buy >= MIN_BUY_PROB:
        signal = "BUY"
        reason = f"매수 확률 {prob_buy:.1%} ≥ 임계값 {MIN_BUY_PROB:.0%}"
    else:
        signal = "HOLD"
        reason = f"매수 확률 {prob_buy:.1%} — 임계값 {MIN_BUY_PROB:.0%} 미달, 관망"

    logger.info(f"[signal] {name}({code}) → {signal} | buy={prob_buy:.1%} | {price:,}원")

    return {
        "signal": signal,
        "reason": reason,
        "price": price,
        "prob_buy": round(prob_buy, 4),
        # 하위 호환용 여집합. 매도 판정 근거로 쓰지 말 것 — 횡보·목표 미달이 섞여 있다.
        "prob_sell": round(1.0 - prob_buy, 4),
        # routes/stock_ml.py 의 LR 폴백과 키 이름은 같다. 단 'signal' 값 어휘는 다르다
        # (여기 BUY/HOLD vs LR '상승'/'하락') — 프론트는 BUY/SELL/HOLD 만 해석한다.
        "prob_up": round(prob_buy * 100, 1),
        "prob_down": round((1.0 - prob_buy) * 100, 1),
        "confidence": round(prob_buy, 4),
        "model_type": f"XGBoost_v2 앙상블({PRIMARY_LABEL})",
        "conf_daily": round(confs.get("daily", 0.0), 4),
        "conf_short": round(confs.get("short", 0.0), 4),
        "conf_swing": round(confs.get("swing", 0.0), 4),
        "ticker": code,
        "ticker_name": name,
        "predicted_at": datetime.now().isoformat(timespec="seconds"),
    }


def get_model_status() -> dict[str, Any]:
    """
    앙상블 로드 상태. routes/stock_ml.py 의 GET /ml/status 응답에 병합된다.

    반환 dict 가 마지막에 병합되므로 'xgb_available' 키로 실제 로드 여부를 덮어쓴다
    (호출 성공만으로 available=True 가 되던 것을 실제 상태로 정정).

    GET /ml/status 는 무인증 엔드포인트다 — 절대경로·예외 원문을 싣지 않는다.
    진단 정보는 logger 로만 남긴다.
    """
    try:
        from XGBoost_v2.daily_recommend import _load_ensemble

        ensemble = _load_ensemble()
    except Exception as e:
        logger.warning(f"[signal] 모델 상태 조회 실패: {e}", exc_info=True)
        return {"xgb_available": False}

    report = _load_report()
    status: dict[str, Any] = {
        "xgb_available": ensemble is not None,
        "xgb_model_dir_exists": MODEL_DIR.exists(),
        "xgb_trained_at": report.get("trained_at"),
        "xgb_use_pit": report.get("use_pit"),
        "xgb_n_features": report.get("n_features"),
        "xgb_buy_threshold": MIN_BUY_PROB,
        "xgb_sell_supported": False,  # 매도 라벨 미학습 — docstring 참고
    }
    if ensemble is not None:
        status["xgb_labels"] = sorted(ensemble["labels"].keys())
        status["xgb_feature_count"] = len(ensemble["features"])
        booster = MODEL_DIR / f"xgb_v2_{PRIMARY_LABEL}.json"
        if booster.exists():
            status["xgb_model_mtime"] = datetime.fromtimestamp(
                booster.stat().st_mtime
            ).isoformat(timespec="seconds")
    return status


def reload_model() -> bool:
    """모델 파일 교체(재학습·증분학습) 후 캐시를 비우고 다시 로드. 성공 여부 반환."""
    try:
        from XGBoost_v2.daily_recommend import _load_ensemble, reload_ensemble

        reload_ensemble()
        ok = _load_ensemble() is not None
        logger.info(f"[signal] 모델 재로드 {'성공' if ok else '실패'}")
        return ok
    except Exception as e:
        logger.error(f"[signal] 모델 재로드 실패: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    print("=== get_model_status() ===")
    for k, v in get_model_status().items():
        print(f"  {k:<22}{v}")
    print()
    print("=== predict('005930', '삼성전자') ===")
    for k, v in predict("005930", "삼성전자").items():
        print(f"  {k:<22}{v}")
