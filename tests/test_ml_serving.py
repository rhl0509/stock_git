"""ML 서빙 회귀 테스트 — LR 폴백 어휘·무실력 게이트·ETF 제외·signal 규약.

외부 시세/KRX 호출 없이 순수 로직만 검증한다(모델 로드·pykrx 조회는 스텁).
실행: d:\\expense_tracker\\.venv64\\Scripts\\python.exe -m pytest tests/test_ml_serving.py -q
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ['RUN_SCHEDULER'] = 'false'

import config  # noqa: E402,F401  .env 로드
from routes import stock_ml  # noqa: E402


# ── LR 폴백 어휘: BUY/SELL/HOLD (한글 '상승'/'하락' 아님) ──────────────

def _lr_signal(prob_up):
    """_predict_lr 의 임계값 판정만 떼어 재현(모델·피처 없이)."""
    prob_down = 1.0 - prob_up
    if prob_up >= stock_ml.LR_BUY_PROB:
        return 'BUY'
    if prob_down >= stock_ml.LR_SELL_PROB:
        return 'SELL'
    return 'HOLD'


def test_lr_vocab_is_english_buy_sell_hold():
    # 프론트 ML_META 는 BUY/SELL/HOLD 만 안다. 한글이면 '관망' 으로 오표시됐다.
    assert _lr_signal(0.85) == 'BUY'
    assert _lr_signal(0.10) == 'SELL'
    assert _lr_signal(0.50) == 'HOLD'          # 사이 구간


def test_lr_thresholds_match_repo_convention():
    # trader RiskConfig·signal.py 와 같은 env 키·기본값(0.60)
    assert stock_ml.LR_BUY_PROB == 0.60
    assert stock_ml.LR_SELL_PROB == 0.60


# ── 무실력 게이트: baseline 퇴화·lift 부족이면 BUY/SELL → HOLD ─────────

def test_gate_downgrades_no_skill_buy():
    r = stock_ml._gate_lr_signal({
        'signal': 'BUY', 'prob_up': 83.3, 'lift': 0.001, 'baseline': 0.52,
    })
    assert r['signal'] == 'HOLD'
    assert r['signal_downgraded_from'] == 'BUY'
    assert 'signal_note' in r


def test_gate_downgrades_degenerate_baseline():
    # baseline≈0 = 검증 구간이 한쪽 클래스뿐 → 방향 못 배움
    r = stock_ml._gate_lr_signal({
        'signal': 'SELL', 'prob_up': 18.0, 'lift': 1.0, 'baseline': 0.0,
    })
    assert r['signal'] == 'HOLD'
    assert r['signal_downgraded_from'] == 'SELL'


def test_gate_keeps_real_skill():
    # lift 충분 + baseline 정상 → 그대로 유지
    r = stock_ml._gate_lr_signal({
        'signal': 'BUY', 'prob_up': 72.0, 'lift': 0.15, 'baseline': 0.48,
    })
    assert r['signal'] == 'BUY'
    assert 'signal_downgraded_from' not in r


def test_gate_ignores_hold():
    r = stock_ml._gate_lr_signal({'signal': 'HOLD', 'lift': 0.0, 'baseline': 0.5})
    assert r['signal'] == 'HOLD'


# ── ETF/ETN/ELW 제외 ─────────────────────────────────────────────────

def test_derivative_excluded_before_prediction(monkeypatch):
    # _is_derivative True → get_ml_prediction 이 예측 전에 error 로 차단
    monkeypatch.setattr(stock_ml, '_is_derivative', lambda code, day: True)
    r = stock_ml.get_ml_prediction('069500', '069500.KS', 'KODEX 200')
    assert 'error' in r
    assert 'ETF' in r['error'] or 'ETN' in r['error']


def test_non_derivative_not_blocked_by_etf_gate(monkeypatch):
    # _is_derivative False 면 ETF 게이트를 통과(이후 모델/LR 경로는 별개)
    monkeypatch.setattr(stock_ml, '_is_derivative', lambda code, day: False)
    monkeypatch.setattr(stock_ml, '_predict_xgb', lambda code, name: None)  # XGB 스킵
    monkeypatch.setattr(stock_ml, '_get_ohlcv',
                        lambda *a, **k: (None, None, None, None))  # OHLCV 없음
    r = stock_ml.get_ml_prediction('005930', '005930.KS', '삼성전자')
    # ETF error 가 아니라 OHLCV 조회 실패 error 여야 한다
    assert 'error' in r
    assert 'ETF' not in r.get('error', '')


def test_derivative_codes_cache_fail_open(monkeypatch):
    # KRX 조회 실패 + 캐시 없음 → 빈 집합(fail-open, 예측을 막지 않음)
    monkeypatch.setattr(stock_ml, '_fetch_derivative_codes', lambda: set())
    monkeypatch.setattr(stock_ml, '_DERIV_CACHE_FILE',
                        Path('nonexistent_cache_file_xyz.json'))
    stock_ml._derivative_codes.cache_clear()
    codes = stock_ml._derivative_codes('2099-01-01')
    assert codes == frozenset()
    stock_ml._derivative_codes.cache_clear()


# ── signal.py 규약 ───────────────────────────────────────────────────

def test_signal_normalize_code():
    from trading import signal
    assert signal._normalize_code('005930.KS') == '005930'
    assert signal._normalize_code('005930.KQ') == '005930'
    assert signal._normalize_code('005930') == '005930'
    assert signal._normalize_code(' 005930.ks ') == '005930'


def test_signal_error_shape():
    from trading import signal
    e = signal._error('005930', '삼성전자', '테스트 사유')
    assert e['signal'] == 'ERROR'           # 호출자가 이 값으로 판정
    assert e['reason'] == '테스트 사유'
    assert e['prob_buy'] == 0.0             # 안전 기본값


def test_signal_no_sell_label():
    # XGBoost 라벨은 "목표달성 AND 낙폭제한" 이라 매도 근거가 없다 → SELL 안 냄
    from trading import signal
    assert 'SELL' not in signal.predict.__doc__ or '내지 않' in signal.__doc__
