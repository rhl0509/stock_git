"""
trading/feature.py
──────────────────────────────────────────────────────────────────────────────
XGBoost 모델에 입력할 피처를 수집·계산하는 파이프라인.

데이터 소스:
  - 키움 API         : OHLCV, 호가, 기관/외국인 순매수
  - 한국투자 API     : 재무 데이터 (PER, PBR, EPS)
  - 한국은행 API     : 기준금리, 환율(USD/KRW), M2
  - 금감원 DART API  : 공시 이벤트 (실적, 유상증자 등)
  - 네이버 뉴스 크롤링: 감성 점수

반환값:
  build_features(ticker, date) → dict[str, float]
    signal.py 에서 이 dict를 받아 XGBoost에 입력함.
──────────────────────────────────────────────────────────────────────────────
"""

import os
import re
import math
import time
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from functools import lru_cache

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 환경변수 / 상수
# ─────────────────────────────────────────────
BOK_API_KEY   = os.getenv("BOK_API_KEY", "")       # 한국은행 ECOS
DART_API_KEY  = os.getenv("DART_API_KEY", "")      # 금감원 DART
KIS_APP_KEY   = os.getenv("KIS_APP_KEY", "")       # 한국투자증권
KIS_APP_SECRET= os.getenv("KIS_APP_SECRET", "")

BOK_BASE  = "https://ecos.bok.or.kr/api"
DART_BASE = "https://opendart.fss.or.kr/api"
KIS_BASE  = "https://openapi.koreainvestment.com:9443"

# 피처 이름 목록 (feature_list.json 생성 시 기준)
FEATURE_COLUMNS = [
    # ── 기술적 지표 ──
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "bb_upper", "bb_lower", "bb_pct",          # Bollinger Band %B
    "obv_norm",                                 # OBV 정규화
    "atr_14",                                   # Average True Range
    "stoch_k", "stoch_d",                       # Stochastic
    "cci_20",                                   # CCI
    "adx_14",                                   # ADX (추세 강도)
    # ── 가격/거래량 파생 ──
    "ret_1d", "ret_5d", "ret_20d",              # 수익률
    "vol_ratio_5",                              # 거래량 / 5일 평균 비율
    "price_vs_ma20", "price_vs_ma60",           # 이격도
    "high52w_pct", "low52w_pct",                # 52주 고/저가 대비 위치
    "gap_open",                                 # 갭 (시가 - 전일종가) / 전일종가
    # ── 수급 ──
    "inst_net_buy",                             # 기관 순매수 (정규화)
    "foreign_net_buy",                          # 외국인 순매수 (정규화)
    "foreign_hold_ratio",                       # 외국인 보유 비율
    # ── 재무 ──
    "per", "pbr", "eps_yoy",                    # PER, PBR, EPS 성장률
    # ── 거시 ──
    "bok_rate",                                 # 기준금리
    "usdkrw",                                   # 환율
    "m2_growth",                                # M2 증가율 (3개월)
    # ── 공시 이벤트 (binary) ──
    "dart_earnings_5d",                         # 5일 내 실적 공시 여부
    "dart_rights_5d",                           # 5일 내 유상증자 여부
    # ── 뉴스 감성 ──
    "news_sentiment",                           # 감성 점수 [-1, 1]
    "news_count_3d",                            # 3일 내 뉴스 수
]


# ═══════════════════════════════════════════════════════════════════════════
# 1. 기술적 지표 계산 (pandas 기반, 외부 라이브러리 의존 최소화)
# ═══════════════════════════════════════════════════════════════════════════

def _calc_rsi(close: pd.Series, period: int = 14) -> float:
    """RSI 계산. close는 최소 period+1 길이 필요."""
    delta = close.diff().dropna()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def _calc_macd(close: pd.Series) -> tuple[float, float, float]:
    """MACD (12, 26, 9). Returns (macd, signal, hist)."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sig   = macd.ewm(span=9, adjust=False).mean()
    hist  = macd - sig
    return float(macd.iloc[-1]), float(sig.iloc[-1]), float(hist.iloc[-1])


def _calc_bollinger(close: pd.Series, period: int = 20) -> tuple[float, float, float]:
    """Bollinger Band. Returns (upper, lower, %B)."""
    ma  = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    pct   = (close - lower) / (upper - lower + 1e-9)
    return float(upper.iloc[-1]), float(lower.iloc[-1]), float(pct.iloc[-1])


def _calc_obv(close: pd.Series, volume: pd.Series) -> float:
    """OBV 정규화 (z-score over 20 bars)."""
    direction = np.sign(close.diff().fillna(0))
    obv = (direction * volume).cumsum()
    z = (obv - obv.rolling(20).mean()) / (obv.rolling(20).std() + 1e-9)
    return float(z.iloc[-1])


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """ATR (Average True Range)."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(com=period - 1, min_periods=period).mean()
    return float(atr.iloc[-1])


def _calc_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                     k_period: int = 14, d_period: int = 3) -> tuple[float, float]:
    """Stochastic %K, %D."""
    lowest  = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest + 1e-9)
    d = k.rolling(d_period).mean()
    return float(k.iloc[-1]), float(d.iloc[-1])


def _calc_cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> float:
    """Commodity Channel Index."""
    tp  = (high + low + close) / 3
    ma  = tp.rolling(period).mean()
    md  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())))
    cci = (tp - ma) / (0.015 * md + 1e-9)
    return float(cci.iloc[-1])


def _calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """ADX (Average Directional Index)."""
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr14    = pd.Series(tr).ewm(com=period - 1, min_periods=period).mean()
    plus_di  = 100 * pd.Series(plus_dm).ewm(com=period - 1).mean() / (atr14 + 1e-9)
    minus_di = 100 * pd.Series(minus_dm).ewm(com=period - 1).mean() / (atr14 + 1e-9)
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx      = dx.ewm(com=period - 1, min_periods=period).mean()
    return float(adx.iloc[-1])


def calc_technical_features(ohlcv_df: pd.DataFrame) -> dict:
    """
    ohlcv_df: columns=['open','high','low','close','volume'], DatetimeIndex, 최소 60행
    → 기술적 지표 dict 반환
    """
    c, h, l, v = ohlcv_df["close"], ohlcv_df["high"], ohlcv_df["low"], ohlcv_df["volume"]

    rsi                       = _calc_rsi(c)
    macd, macd_sig, macd_hist = _calc_macd(c)
    bb_upper, bb_lower, bb_pct= _calc_bollinger(c)
    obv_norm                  = _calc_obv(c, v)
    atr_14                    = _calc_atr(h, l, c)
    stoch_k, stoch_d          = _calc_stochastic(h, l, c)
    cci_20                    = _calc_cci(h, l, c)
    adx_14                    = _calc_adx(h, l, c)

    # 수익률
    ret_1d  = float((c.iloc[-1] / c.iloc[-2]  - 1) if len(c) > 1  else 0)
    ret_5d  = float((c.iloc[-1] / c.iloc[-6]  - 1) if len(c) > 5  else 0)
    ret_20d = float((c.iloc[-1] / c.iloc[-21] - 1) if len(c) > 20 else 0)

    # 거래량 비율
    vol_ratio_5 = float(v.iloc[-1] / (v.iloc[-6:-1].mean() + 1e-9))

    # 이격도
    ma20 = c.rolling(20).mean().iloc[-1]
    ma60 = c.rolling(60).mean().iloc[-1]
    price_vs_ma20 = float(c.iloc[-1] / (ma20 + 1e-9) - 1)
    price_vs_ma60 = float(c.iloc[-1] / (ma60 + 1e-9) - 1)

    # 52주 고/저가 대비
    high52 = h.rolling(252).max().iloc[-1]
    low52  = l.rolling(252).min().iloc[-1]
    high52w_pct = float(c.iloc[-1] / (high52 + 1e-9) - 1)
    low52w_pct  = float(c.iloc[-1] / (low52  + 1e-9) - 1)

    # 갭
    gap_open = float((ohlcv_df["open"].iloc[-1] - c.iloc[-2]) / (c.iloc[-2] + 1e-9))

    return {
        "rsi_14": rsi, "macd": macd, "macd_signal": macd_sig, "macd_hist": macd_hist,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_pct": bb_pct,
        "obv_norm": obv_norm, "atr_14": atr_14,
        "stoch_k": stoch_k, "stoch_d": stoch_d,
        "cci_20": cci_20, "adx_14": adx_14,
        "ret_1d": ret_1d, "ret_5d": ret_5d, "ret_20d": ret_20d,
        "vol_ratio_5": vol_ratio_5,
        "price_vs_ma20": price_vs_ma20, "price_vs_ma60": price_vs_ma60,
        "high52w_pct": high52w_pct, "low52w_pct": low52w_pct,
        "gap_open": gap_open,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. 수급 피처 (키움 API 래퍼 — routes/kiwoom.py 에서 데이터 가져옴)
# ═══════════════════════════════════════════════════════════════════════════

def calc_supply_features(ticker: str, kiwoom_client=None) -> dict:
    """
    키움 API (OPT10059 / OPT10060) 에서 기관/외국인 순매수 조회.
    kiwoom_client: routes/kiwoom.py 의 Kiwoom 인스턴스 (없으면 0 반환)

    정규화: 최근 20일 순매수 중 오늘 값의 z-score
    """
    result = {
        "inst_net_buy": 0.0,
        "foreign_net_buy": 0.0,
        "foreign_hold_ratio": 0.0,
    }
    if kiwoom_client is None:
        logger.warning("[supply] kiwoom_client 없음 → 수급 피처 0으로 대체")
        return result

    try:
        # ── 기관 순매수 (OPT10059) ──
        inst_data    = kiwoom_client.get_investor_trend(ticker, "기관")
        inst_series  = pd.Series(inst_data)
        result["inst_net_buy"] = float(
            (inst_series.iloc[-1] - inst_series.mean()) / (inst_series.std() + 1e-9)
        )

        # ── 외국인 순매수 (OPT10060) ──
        foreign_data  = kiwoom_client.get_investor_trend(ticker, "외국인")
        foreign_series = pd.Series(foreign_data)
        result["foreign_net_buy"] = float(
            (foreign_series.iloc[-1] - foreign_series.mean()) / (foreign_series.std() + 1e-9)
        )

        # ── 외국인 보유 비율 ──
        result["foreign_hold_ratio"] = kiwoom_client.get_foreign_hold_ratio(ticker)

    except Exception as e:
        logger.error(f"[supply] 수급 데이터 조회 실패 ({ticker}): {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 3. 재무 피처 (한국투자 API)
# ═══════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=256)
def _get_kis_token() -> str:
    """한국투자증권 OAuth 토큰 (캐시, 하루 1회 갱신 권장)."""
    url  = f"{KIS_BASE}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
    }
    res = requests.post(url, json=body, timeout=5)
    res.raise_for_status()
    return res.json()["access_token"]


def calc_financial_features(ticker: str) -> dict:
    """
    한국투자 API → PER, PBR, EPS YoY 성장률.
    실패 시 중립값 반환 (모델이 이 피처를 무시하도록 NaN 대신 -1 사용).
    """
    result = {"per": -1.0, "pbr": -1.0, "eps_yoy": 0.0}
    try:
        token  = _get_kis_token()
        url    = f"{KIS_BASE}/uapi/domestic-stock/v1/finance/financial-ratio"
        params = {
            "fid_div_cls_code": "0",
            "fid_input_iscd": ticker,
        }
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": "FHKST66430300",
        }
        res  = requests.get(url, params=params, headers=headers, timeout=5)
        data = res.json().get("output", [{}])

        if len(data) >= 2:
            per_now  = float(data[0].get("per",  0) or 0)
            pbr_now  = float(data[0].get("pbr",  0) or 0)
            eps_now  = float(data[0].get("eps",  0) or 0)
            eps_prev = float(data[1].get("eps",  1) or 1)
            result["per"]     = per_now
            result["pbr"]     = pbr_now
            result["eps_yoy"] = (eps_now - eps_prev) / (abs(eps_prev) + 1e-9)

    except Exception as e:
        logger.error(f"[financial] 재무 데이터 조회 실패 ({ticker}): {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 4. 거시 피처 (한국은행 ECOS API)
# ═══════════════════════════════════════════════════════════════════════════

# 한국은행 ECOS 통계 코드
_BOK_STAT = {
    "rate":  ("722Y001", "0101000"),   # 기준금리
    "usdkrw":("731Y003", "0000001"),   # USD/KRW
    "m2":    ("101Y002", "BBHS00"),    # M2 (평잔)
}


@lru_cache(maxsize=32)
def _fetch_bok(stat_code: str, item_code: str, count: int = 6) -> list[float]:
    """한국은행 ECOS API에서 최근 count개 월간 시계열 조회."""
    today = datetime.today()
    start = (today - timedelta(days=count * 35)).strftime("%Y%m")
    end   = today.strftime("%Y%m")
    url   = (
        f"{BOK_BASE}/StatisticSearch/{BOK_API_KEY}/json/kr/1/{count+2}/"
        f"{stat_code}/MM/{start}/{end}/{item_code}"
    )
    try:
        res  = requests.get(url, timeout=5)
        rows = res.json()["StatisticSearch"]["row"]
        return [float(r["DATA_VALUE"].replace(",", "") or 0) for r in rows]
    except Exception as e:
        logger.error(f"[BOK] 조회 실패 ({stat_code}): {e}")
        return [0.0] * count


def calc_macro_features() -> dict:
    """
    한국은행 ECOS → 기준금리, 환율, M2 증가율.
    lru_cache로 동일 세션 내 반복 호출 최소화.
    """
    rate_series  = _fetch_bok(*_BOK_STAT["rate"])
    fx_series    = _fetch_bok(*_BOK_STAT["usdkrw"])
    m2_series    = _fetch_bok(*_BOK_STAT["m2"], count=5)

    bok_rate  = float(rate_series[-1]) if rate_series else 0.0
    usdkrw    = float(fx_series[-1])   if fx_series   else 1300.0

    # M2 3개월 증가율
    if len(m2_series) >= 4:
        m2_growth = (m2_series[-1] - m2_series[-4]) / (m2_series[-4] + 1e-9)
    else:
        m2_growth = 0.0

    return {
        "bok_rate":  bok_rate,
        "usdkrw":    usdkrw,
        "m2_growth": m2_growth,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. 공시 이벤트 피처 (금감원 DART API)
# ═══════════════════════════════════════════════════════════════════════════

def _get_dart_corp_code(ticker: str) -> str | None:
    """종목코드 → DART 고유번호 변환 (corpCode.xml 사용)."""
    # 실운영에서는 corpCode.xml 파싱 결과를 DB에 캐싱 권장
    url = f"{DART_BASE}/corpCode.xml?crtfc_key={DART_API_KEY}"
    try:
        import zipfile, io
        res  = requests.get(url, timeout=10)
        zf   = zipfile.ZipFile(io.BytesIO(res.content))
        xml  = zf.read("CORPCODE.xml").decode("utf-8")
        soup = BeautifulSoup(xml, "xml")
        for item in soup.find_all("list"):
            if item.find("stock_code") and item.find("stock_code").text == ticker:
                return item.find("corp_code").text
    except Exception as e:
        logger.error(f"[DART] corp_code 조회 실패: {e}")
    return None


def calc_dart_features(ticker: str, target_date: datetime | None = None) -> dict:
    """
    DART 공시 API → 5일 내 실적·유상증자 공시 여부 (binary 0/1).
    target_date: 피처 기준일 (None이면 오늘)
    """
    result = {"dart_earnings_5d": 0, "dart_rights_5d": 0}
    if not DART_API_KEY:
        logger.warning("[DART] API 키 없음")
        return result

    target = target_date or datetime.today()
    start  = (target - timedelta(days=5)).strftime("%Y%m%d")
    end    = target.strftime("%Y%m%d")

    corp_code = _get_dart_corp_code(ticker)
    if not corp_code:
        return result

    try:
        url    = f"{DART_BASE}/list.json"
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bgn_de": start,
            "end_de": end,
            "pblntf_ty": "A",           # 정기공시
            "page_count": 20,
        }
        res   = requests.get(url, params=params, timeout=5)
        items = res.json().get("list", [])

        for item in items:
            report = item.get("report_nm", "")
            if any(k in report for k in ["실적", "분기보고", "사업보고", "반기보고"]):
                result["dart_earnings_5d"] = 1
            if any(k in report for k in ["유상증자", "신주"]):
                result["dart_rights_5d"] = 1

    except Exception as e:
        logger.error(f"[DART] 공시 조회 실패 ({ticker}): {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 6. 뉴스 감성 피처 (네이버 뉴스 크롤링)
# ═══════════════════════════════════════════════════════════════════════════

# 간단한 규칙 기반 감성 사전 (FinBERT-KR 사용 가능 환경이면 교체 권장)
_POS_WORDS = ["급등", "신고가", "실적호조", "매수", "상승", "흑자전환", "기대", "수주"]
_NEG_WORDS = ["급락", "하락", "매도", "적자", "위기", "소송", "부도", "리콜", "하한가"]


def _simple_sentiment(text: str) -> float:
    """
    규칙 기반 감성 점수. 범위: [-1, 1]
    TODO: FinBERT-KR 또는 KLUE-BERT 파인튜닝 모델로 교체 권장
    """
    pos = sum(1 for w in _POS_WORDS if w in text)
    neg = sum(1 for w in _NEG_WORDS if w in text)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def calc_news_features(ticker_name: str, days: int = 3) -> dict:
    """
    네이버 뉴스 검색 크롤링 → 감성 점수, 뉴스 수.
    ticker_name: 종목명 (예: "삼성전자") — 코드보다 검색 품질 높음
    days: 최근 n일 이내 뉴스만 수집

    ⚠️ 실운영 시 네이버 검색 로봇 차단 주의 → User-Agent 헤더 + 딜레이 필수
    """
    result = {"news_sentiment": 0.0, "news_count_3d": 0}
    today  = datetime.today()
    cutoff = today - timedelta(days=days)

    try:
        url     = "https://search.naver.com/search.naver"
        params  = {"where": "news", "query": ticker_name, "sort": "1"}  # sort=1: 최신순
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        }
        res  = requests.get(url, params=params, headers=headers, timeout=7)
        soup = BeautifulSoup(res.text, "html.parser")

        scores = []
        for item in soup.select("div.news_wrap"):
            # ── 날짜 파싱 ──
            date_tag = item.select_one("span.info")
            if not date_tag:
                continue
            date_text = date_tag.text.strip()
            # 네이버는 "n분 전", "n시간 전", "YYYY.MM.DD." 형식 혼재
            if "분 전" in date_text or "시간 전" in date_text:
                pub_date = today
            elif re.match(r"\d{4}\.\d{2}\.\d{2}", date_text):
                pub_date = datetime.strptime(date_text[:10], "%Y.%m.%d")
            else:
                continue

            if pub_date < cutoff:
                continue

            # ── 텍스트 수집 ──
            title   = (item.select_one("a.news_tit") or item).get_text(strip=True)
            summary = (item.select_one("div.dsc_wrap")  or item).get_text(strip=True)
            score   = _simple_sentiment(title + " " + summary)
            scores.append(score)

            time.sleep(0.05)    # 과도한 요청 방지

        result["news_count_3d"] = len(scores)
        result["news_sentiment"] = float(np.mean(scores)) if scores else 0.0

    except Exception as e:
        logger.error(f"[news] 뉴스 크롤링 실패 ({ticker_name}): {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 7. 메인 진입점 — 전체 피처 빌드
# ═══════════════════════════════════════════════════════════════════════════

def build_features(
    ticker: str,
    ticker_name: str,
    ohlcv_df: pd.DataFrame,
    kiwoom_client=None,
    target_date: datetime | None = None,
) -> dict[str, float]:
    """
    모든 피처를 수집·계산해 signal.py가 소비할 dict 반환.

    Args:
        ticker       : 종목코드 (예: "005930")
        ticker_name  : 종목명   (예: "삼성전자")
        ohlcv_df     : 키움/KIS에서 받은 OHLCV DataFrame (최소 60행)
        kiwoom_client: routes/kiwoom.py 의 Kiwoom 인스턴스 (None이면 수급 피처 0)
        target_date  : 피처 기준일 (None이면 오늘)

    Returns:
        FEATURE_COLUMNS 순서로 정렬된 dict[str, float]
        (signal.py 에서 feature_list.json 순서와 맞춰야 함)
    """
    features: dict = {}

    # ── 1. 기술적 지표 ──
    try:
        features.update(calc_technical_features(ohlcv_df))
    except Exception as e:
        logger.error(f"[build] 기술적 지표 실패: {e}")

    # ── 2. 수급 ──
    try:
        features.update(calc_supply_features(ticker, kiwoom_client))
    except Exception as e:
        logger.error(f"[build] 수급 피처 실패: {e}")

    # ── 3. 재무 ──
    try:
        features.update(calc_financial_features(ticker))
    except Exception as e:
        logger.error(f"[build] 재무 피처 실패: {e}")

    # ── 4. 거시 ──
    try:
        features.update(calc_macro_features())
    except Exception as e:
        logger.error(f"[build] 거시 피처 실패: {e}")

    # ── 5. 공시 ──
    try:
        features.update(calc_dart_features(ticker, target_date))
    except Exception as e:
        logger.error(f"[build] DART 피처 실패: {e}")

    # ── 6. 뉴스 감성 ──
    try:
        features.update(calc_news_features(ticker_name))
    except Exception as e:
        logger.error(f"[build] 뉴스 피처 실패: {e}")

    # ── FEATURE_COLUMNS 순서로 정렬 & 누락 피처는 0.0 대체 ──
    ordered = {}
    for col in FEATURE_COLUMNS:
        val = features.get(col, 0.0)
        # NaN / Inf 방어
        if not math.isfinite(val):
            val = 0.0
        ordered[col] = val

    logger.info(f"[build] {ticker} 피처 완성: {len(ordered)}개")
    return ordered


# ═══════════════════════════════════════════════════════════════════════════
# 8. 학습용 배치 피처 생성 (모델 훈련 시 사용)
# ═══════════════════════════════════════════════════════════════════════════

def build_feature_matrix(
    ticker: str,
    ticker_name: str,
    ohlcv_df: pd.DataFrame,
    kiwoom_client=None,
    lookback: int = 252,
) -> pd.DataFrame:
    """
    Walk-forward 학습을 위한 날짜별 피처 매트릭스 생성.

    ohlcv_df 에서 날짜를 순차적으로 슬라이딩하며 build_features()를 호출.
    결과: shape = (lookback, len(FEATURE_COLUMNS))

    ⚠️ 이 함수는 학습 시에만 호출. 실시간 예측은 build_features() 사용.
    """
    rows = []
    dates = ohlcv_df.index.tolist()

    # 최소 60행 데이터가 확보되는 시점부터 피처 계산
    for i in range(60, min(len(dates), 60 + lookback)):
        window = ohlcv_df.iloc[:i]
        target = dates[i]
        row    = build_features(
            ticker, ticker_name, window,
            kiwoom_client=kiwoom_client,
            target_date=target,
        )
        row["date"] = target
        rows.append(row)

    df = pd.DataFrame(rows).set_index("date")
    return df[FEATURE_COLUMNS]   # 컬럼 순서 고정