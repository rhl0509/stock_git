"""
feature_v2.py — 53개 통합 피처 빌드 (v2.1).

v2.0 → v2.1 변경:
  기술적 피처  24 → 32개:
    + rsi_lag1, rsi_lag5              (RSI 시차 피처)
    + macd_hist_lag5, vol_ratio_lag5  (MACD·거래량 시차)
    + vol_cluster, std_cluster        (변동성 클러스터링)
    + ret_vs_market, rsi_vs_market    (시장 상대 강도)
  공시 피처     4 → 5개:
    + days_since_disclosure           (이벤트 시차)
  재무 피처    11개 — PIT(Point-in-Time) 매칭 지원
  거시 피처     5개 (변경 없음)
  = 총 53개  (기존 모델과 호환 불가 → 재학습 필요)
"""
import logging
import numpy as np
import pandas as pd

from .quant_gate import compute_hurst

from .fmp_client        import (get_financial_features, get_financial_features_pit,
                               FINANCIAL_COLS)
from .dart_client       import get_disclosure_features, DISCLOSURE_COLS
from .naver_news        import get_news_features,       NEWS_COLS
from .bok_client        import get_macro_features,      MACRO_COLS as _BOK_MACRO_COLS
from .investor_features import get_investor_features,   INVESTOR_COLS
from .short_features    import get_short_features,      SHORT_COLS
from .global_features   import get_global_features,     GLOBAL_COLS
from .sector_features   import get_sector_features,     SECTOR_COLS

MACRO_COLS = _BOK_MACRO_COLS + GLOBAL_COLS

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# KOSPI 시장 데이터 (상대 강도 피처용)
# ═══════════════════════════════════════════════════════════════════════════

_market_cache: dict = {}   # {"^KS11": DataFrame}


def get_market_ohlcv(symbol: str = "^KS11") -> pd.DataFrame | None:
    """KOSPI 지수 일봉 로드 (yfinance, 캐시 1회)."""
    if symbol in _market_cache:
        return _market_cache[symbol]
    try:
        import yfinance as yf
        from datetime import datetime, timedelta
        end   = datetime.now()
        start = end - timedelta(days=1800)
        raw   = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False)
        if raw is None or raw.empty:
            return None
        df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index   = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index()
        _market_cache[symbol] = df
        return df
    except Exception as e:
        logger.warning(f"[feature] KOSPI 데이터 로드 실패: {e}")
        return None


def _compute_rsi(c: pd.Series, period: int = 14) -> pd.Series:
    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss  = (-delta).clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-9))


# ═══════════════════════════════════════════════════════════════════════════
# 기술적 지표 32개
# ═══════════════════════════════════════════════════════════════════════════

def build_technical(df: pd.DataFrame,
                    market_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    개별 종목 기술 피처 32개.

    Args:
        df:        종목 OHLCV (index=DatetimeIndex)
        market_df: KOSPI OHLCV — 시장 상대 강도 피처용 (없으면 0으로 채움)
    """
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    feats = {}

    # ── 기존 24개 ──────────────────────────────────────────────────────────
    for d in [1, 5, 20]:
        feats[f"ret_{d}d"] = c.pct_change(d)
    feats["gap_open"] = (df["open"] - c.shift(1)) / (c.shift(1) + 1e-9)
    for w in [5, 10, 20, 60]:
        feats[f"ma{w}_gap"] = c / (c.rolling(w).mean() + 1e-9) - 1

    rsi14 = _compute_rsi(c, 14)
    feats["rsi_14"] = rsi14

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    msig  = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - msig
    feats["macd"]       = macd
    feats["macd_hist"]  = macd_hist
    feats["macd_cross"] = (macd > msig).astype(float)

    ma20  = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    feats["bb_pct"]       = (c - (ma20 - 2 * std20)) / (4 * std20 + 1e-9)
    feats["vol_ratio_5"]  = v / (v.rolling(5).mean()  + 1e-9)
    vol_ratio_20 = v / (v.rolling(20).mean() + 1e-9)
    feats["vol_ratio_20"] = vol_ratio_20

    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    feats["atr_ratio"] = tr.rolling(14).mean() / (c + 1e-9)

    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    feats["obv_norm"] = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-9)

    feats["chan_pos"]    = (c - l.rolling(20).min()) / (
        h.rolling(20).max() - l.rolling(20).min() + 1e-9)
    feats["high52w_pct"] = c / (h.rolling(min(252, len(h))).max() + 1e-9) - 1
    feats["low52w_pct"]  = c / (l.rolling(min(252, len(l))).min() + 1e-9) - 1

    sk = 100 * (c - l.rolling(14).min()) / (
        h.rolling(14).max() - l.rolling(14).min() + 1e-9)
    feats["stoch_k"] = sk
    feats["stoch_d"] = sk.rolling(3).mean()

    tp = (h + l + c) / 3
    feats["cci_20"] = (tp - tp.rolling(20).mean()) / (
        0.015 * tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())),
                                      raw=True) + 1e-9)

    up  = h.diff(); dn = -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0), index=c.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0), index=c.index)
    atr14 = tr.ewm(com=13, min_periods=14).mean()
    pdi = 100 * pdm.ewm(com=13).mean() / (atr14 + 1e-9)
    mdi = 100 * mdm.ewm(com=13).mean() / (atr14 + 1e-9)
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-9)
    feats["adx_14"] = dx.ewm(com=13, min_periods=14).mean()

    # ── 신규 8개 ───────────────────────────────────────────────────────────

    # 시차 피처 (추세 가속도)
    feats["rsi_lag1"]       = rsi14.shift(1)
    feats["rsi_lag5"]       = rsi14.shift(5)
    feats["macd_hist_lag5"] = macd_hist.shift(5)
    feats["vol_ratio_lag5"] = vol_ratio_20.shift(5)

    # 변동성 클러스터링 (폭풍전야 vs 과열 구분)
    atr5  = tr.rolling(5).mean()
    atr20 = tr.rolling(20).mean()
    feats["vol_cluster"] = atr5 / (atr20 + 1e-9)   # 1 초과 = 단기 변동성 급증

    std5  = c.rolling(5).std()
    feats["std_cluster"] = std5 / (std20 + 1e-9)    # 1 초과 = 단기 횡보 붕괴

    # 시장 상대 강도 (KOSPI 대비)
    if market_df is not None and not market_df.empty:
        mkt_c = market_df["close"].reindex(df.index, method="ffill")
        mkt_ret20 = mkt_c.pct_change(20)
        mkt_rsi   = _compute_rsi(mkt_c, 14)
        feats["ret_vs_market"] = c.pct_change(20) - mkt_ret20
        feats["rsi_vs_market"] = rsi14 - mkt_rsi.reindex(df.index)
    else:
        feats["ret_vs_market"] = pd.Series(0.0, index=c.index)
        feats["rsi_vs_market"] = pd.Series(0.0, index=c.index)

    # 글로벌 동조화 (S&P500 20일 롤링 상관계수)
    sp500_df = get_market_ohlcv("^GSPC")
    if sp500_df is not None and not sp500_df.empty:
        sp_c = sp500_df["close"].reindex(df.index, method="ffill")
        feats["corr_sp500_20d"] = c.pct_change().rolling(20).corr(sp_c.pct_change())
    else:
        feats["corr_sp500_20d"] = pd.Series(0.0, index=c.index)

    # ── Hurst 지수 + 시장 체제 ──────────────────────────────────────────────
    feats["hurst"] = pd.Series(compute_hurst(c), index=c.index)

    ma200      = c.rolling(200, min_periods=60).mean()
    vol20_ann  = c.pct_change().rolling(20).std() * np.sqrt(252)
    vol252_ann = c.pct_change().rolling(252, min_periods=60).std() * np.sqrt(252)
    feats["regime_bull"]    = (c > ma200).astype(float)
    feats["regime_vol_low"] = (vol20_ann < vol252_ann * 1.2).astype(float)

    feat_df = pd.DataFrame(feats, index=df.index)
    return feat_df.replace([np.inf, -np.inf], 0).fillna(0)


TECHNICAL_COLS = [
    # 기존 24개
    "ret_1d", "ret_5d", "ret_20d", "gap_open",
    "ma5_gap", "ma10_gap", "ma20_gap", "ma60_gap",
    "rsi_14", "macd", "macd_hist", "macd_cross",
    "bb_pct", "vol_ratio_5", "vol_ratio_20", "atr_ratio",
    "obv_norm", "chan_pos", "high52w_pct", "low52w_pct",
    "stoch_k", "stoch_d", "cci_20", "adx_14",
    # 신규 8개
    "rsi_lag1", "rsi_lag5", "macd_hist_lag5", "vol_ratio_lag5",
    "vol_cluster", "std_cluster",
    "ret_vs_market", "rsi_vs_market",
    # 글로벌 동조화
    "corr_sp500_20d",
    # Hurst + 시장 체제
    "hurst", "regime_bull", "regime_vol_low",
]


# ═══════════════════════════════════════════════════════════════════════════
# 정적 피처 (종목별 1회 조회 — 재무/공시/뉴스)
# ═══════════════════════════════════════════════════════════════════════════

def build_static_features(code: str, name: str, market: str = "KOSPI",
                          as_of_date: pd.Timestamp | None = None) -> dict:
    """
    종목별 정적 피처.

    as_of_date 가 주어지면 PIT(Point-in-Time) 재무 데이터 사용.
    None 이면 최신 데이터 사용 (예측/일별 추천 시).
    """
    if as_of_date is not None:
        fin = get_financial_features_pit(code, market, as_of_date)
    else:
        fin = get_financial_features(code, market)
    disc = get_disclosure_features(code, days=90)
    news = get_news_features(code, name)
    inv    = get_investor_features(code)
    short  = get_short_features(code)
    sector = get_sector_features(code)
    return {**fin, **disc, **news, **inv, **short, **sector}


STATIC_COLS = FINANCIAL_COLS + DISCLOSURE_COLS + NEWS_COLS + INVESTOR_COLS + SHORT_COLS + SECTOR_COLS


# ═══════════════════════════════════════════════════════════════════════════
# 거시 피처 (전역 1회 조회)
# ═══════════════════════════════════════════════════════════════════════════

def get_macro() -> dict:
    return {**get_macro_features(), **get_global_features()}


# ═══════════════════════════════════════════════════════════════════════════
# 통합 피처 컬럼 순서  (53개 = 32 + 11 + 5 + 5)
# ═══════════════════════════════════════════════════════════════════════════

FULL_COLS = TECHNICAL_COLS + STATIC_COLS + MACRO_COLS


# ═══════════════════════════════════════════════════════════════════════════
# 학습/예측용 헬퍼
# ═══════════════════════════════════════════════════════════════════════════

def build_full_row(tech_row: pd.Series, static: dict, macro: dict) -> np.ndarray:
    """단일 시점 피처 벡터 (1-D ndarray, FULL_COLS 순서)."""
    row = []
    for col in FULL_COLS:
        if col in tech_row.index:
            v = tech_row[col]
        elif col in static:
            v = static[col]
        elif col in macro:
            v = macro[col]
        else:
            v = 0.0
        try:
            v = float(v)
        except Exception:
            v = 0.0
        if not np.isfinite(v):
            v = 0.0
        row.append(v)
    return np.array(row, dtype=np.float32)


def build_full_matrix(tech_df: pd.DataFrame, static: dict,
                      macro: dict) -> pd.DataFrame:
    """기술 피처 DataFrame에 정적+거시 피처를 모든 행에 복제."""
    df = tech_df.copy()
    for col in STATIC_COLS:
        df[col] = static.get(col, 0.0)
    for col in MACRO_COLS:
        df[col] = macro.get(col, 0.0)
    return df[FULL_COLS].replace([np.inf, -np.inf], 0).fillna(0)


def build_full_matrix_pit(tech_df: pd.DataFrame,
                          quarterly_history: list[dict],
                          disc_news: dict,
                          macro: dict) -> pd.DataFrame:
    """
    PIT(Point-in-Time) 재무 매칭 행렬 빌드.

    각 행의 날짜 기준으로 해당 시점에 공시됐을 가장 최신 분기 재무를 선택.
    공시 추정 = period_end + 45일 (한국 기업 평균 신고 기한).
    """
    df = tech_df.copy()

    # 분기 히스토리를 period_end 기준 오름차순 정렬
    history_sorted = sorted(quarterly_history,
                             key=lambda q: q.get("period_end", ""))

    for col in MACRO_COLS:
        df[col] = macro.get(col, 0.0)

    # 공시/뉴스/수급/공매도 정적 (PIT 미지원 — 현재 시점 값 브로드캐스트)
    for col in DISCLOSURE_COLS + NEWS_COLS + INVESTOR_COLS + SHORT_COLS + SECTOR_COLS:
        df[col] = disc_news.get(col, 0.0)

    # 재무: 날짜별 PIT 매칭
    fin_defaults = {c: 0.0 for c in FINANCIAL_COLS}
    if not history_sorted:
        for col in FINANCIAL_COLS:
            df[col] = 0.0
    else:
        for idx_date in df.index:
            filing_cutoff = idx_date
            pit = fin_defaults.copy()
            for q in history_sorted:
                try:
                    est_filing = pd.Timestamp(q["period_end"]) + pd.Timedelta(days=45)
                except Exception:
                    continue
                if est_filing <= filing_cutoff:
                    pit = q
            for col in FINANCIAL_COLS:
                df.loc[idx_date, col] = float(pit.get(col, 0.0) or 0.0)

    return df[FULL_COLS].replace([np.inf, -np.inf], 0).fillna(0)


if __name__ == '__main__':
    print(f"총 피처 수: {len(FULL_COLS)}")
    print(f"  기술적: {len(TECHNICAL_COLS)}")
    print(f"  재무  : {len(FINANCIAL_COLS)}")
    print(f"  공시  : {len(DISCLOSURE_COLS)}")
    print(f"  뉴스  : {len(NEWS_COLS)}")
    print(f"  거시  : {len(MACRO_COLS)}")
