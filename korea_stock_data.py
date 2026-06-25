"""
Korea Stock Data Collector
==========================
한국 주식 분석용 통합 데이터 수집 모듈.

소스
----
1. KRX (pykrx)            : 가격, 수급(외국인/기관/개인), 공매도, PER/PBR
2. FinanceDataReader      : 전체 종목 리스트, 인덱스, 보조 가격 데이터
3. 네이버 금융 (크롤링)   : 컨센서스, 추정 실적
4. FnGuide (크롤링)       : 정밀 재무제표, 투자지표
5. FRED                   : 미국 거시지표 (금리, VIX, 환율, 유가)

설치
----
    pip install pykrx finance-datareader fredapi requests beautifulsoup4 lxml pandas

환경변수
--------
    FRED_API_KEY    https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()  # .env 파일에서 FRED_API_KEY 등 환경변수 로드


# ============================================================
# 공통 헬퍼
# ============================================================
def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    return s


def _polite_sleep(seconds: float = 0.4) -> None:
    """크롤링 시 서버 부하 방지."""
    time.sleep(seconds)


# ============================================================
# 1. KRX  (pykrx)
# ============================================================
class KRXSource:
    """KRX 공식 데이터를 긁어오는 pykrx 래퍼.
    한국 시장 분석의 베이스라인. 수급/공매도까지 다 됨."""

    def __init__(self) -> None:
        from pykrx import stock
        self._s = stock

    # --- 종목 메타 ---
    def tickers(self, market: str = "ALL") -> list[str]:
        """market: 'KOSPI' | 'KOSDAQ' | 'ALL'"""
        if market == "ALL":
            return (self._s.get_market_ticker_list(market="KOSPI")
                    + self._s.get_market_ticker_list(market="KOSDAQ"))
        return self._s.get_market_ticker_list(market=market)

    def name(self, ticker: str) -> str:
        return self._s.get_market_ticker_name(ticker)

    # --- 시세 ---
    def ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """일별 OHLCV. 날짜는 'YYYYMMDD'."""
        return self._s.get_market_ohlcv(start, end, ticker)

    # --- 밸류에이션 ---
    def valuation(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """PER, PBR, EPS, BPS, DIV(배당수익률), DPS"""
        return self._s.get_market_fundamental(start, end, ticker)

    # --- 수급 (한국 시장 알파의 핵심) ---
    def investor_flow(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """투자자별 순매수 금액 (외국인/기관/개인/연기금 등)"""
        return self._s.get_market_trading_value_by_date(start, end, ticker)

    def investor_flow_volume(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """투자자별 순매수 수량"""
        return self._s.get_market_trading_volume_by_date(start, end, ticker)

    def foreign_holding(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """외국인 보유 수량 / 한도소진율"""
        return self._s.get_exhaustion_rates_of_foreign_investment(start, end, ticker)

    # --- 공매도 ---
    def short_balance(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """공매도 잔고 (잔고수량/잔고금액/비중)"""
        return self._s.get_shorting_balance_by_date(start, end, ticker)

    def short_volume(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """공매도 거래량/거래대금/비중"""
        return self._s.get_shorting_volume_by_date(start, end, ticker)

    # --- 시장 전체 스냅샷 (팩터 모델 베이스) ---
    def market_cap_snapshot(self, date: str, market: str = "ALL") -> pd.DataFrame:
        """특정일 전체 종목 시가총액 + 거래대금. 유니버스 필터링용."""
        return self._s.get_market_cap(date, market=market)

    def fundamental_snapshot(self, date: str, market: str = "ALL") -> pd.DataFrame:
        """특정일 전체 종목 PER/PBR/배당수익률. 팩터 점수화 베이스."""
        return self._s.get_market_fundamental(date, market=market)

    # --- KRX 시장 전체 스냅샷이 차단됐을 때의 우회 ---
    def ohlcv_one(self, ticker: str, date: str) -> pd.DataFrame:
        """단일 종목 단일일 OHLCV (시장 스냅샷 우회용)."""
        return self._s.get_market_ohlcv(date, date, ticker)


# ============================================================
# 2. FinanceDataReader
# ============================================================
class FDRSource:
    """깔끔한 가격 API + 한국/해외 인덱스. 종목 리스트도 메타정보 풍부."""

    def __init__(self) -> None:
        import FinanceDataReader as fdr
        self._fdr = fdr

    def listing(self, market: str = "KRX") -> pd.DataFrame:
        """전체 종목 + 메타. market: 'KRX', 'KOSPI', 'KOSDAQ', 'KONEX', 'KRX-DELISTING' 등.
        Sector/Industry 컬럼 포함되어 업종 필터링에 유용."""
        return self._fdr.StockListing(market)

    def price(self, ticker: str, start: str, end: Optional[str] = None) -> pd.DataFrame:
        """일별 OHLCV. ticker는 종목코드(005930) 또는 인덱스(KS11/KQ11) 모두 가능."""
        return self._fdr.DataReader(ticker, start, end)


# ============================================================
# 3. 네이버 금융 (비공식 크롤링 - HTML 변경 시 깨질 수 있음)
# ============================================================
class NaverFinanceSource:
    BASE = "https://finance.naver.com/item/main.naver?code={code}"

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._sess = session or _make_session()

    def _fetch(self, url: str) -> str:
        r = self._sess.get(url, timeout=10)
        r.encoding = "euc-kr"
        return r.text

    def consensus(self, ticker: str) -> dict:
        """투자의견 + 목표주가 (애널리스트 평균).
        네이버 페이지 구조 변경에 대비해 다중 셀렉터 시도."""
        html = self._fetch(self.BASE.format(code=ticker))
        soup = BeautifulSoup(html, "lxml")
        out: dict = {"ticker": ticker, "investment_opinion": None, "target_price": None}

        # 시도 1: 추정컨센서스 박스
        try:
            box = soup.select_one("#tab_con1 .gray")
            if box:
                ems = [e.get_text(strip=True) for e in box.select("em")]
                if len(ems) >= 1: out["investment_opinion"] = ems[0]
                if len(ems) >= 2: out["target_price"] = ems[1]
        except Exception as e:
            out["error_step1"] = str(e)

        # 시도 2: 페이지 텍스트에서 정규식 검색 (폴백)
        if not out["target_price"]:
            try:
                txt = soup.get_text(" ", strip=True)
                m = re.search(r"목표주가\s*([\d,]+)", txt)
                if m:
                    out["target_price"] = m.group(1)
                m2 = re.search(r"투자의견\s*([가-힣A-Za-z\.]+)", txt)
                if m2:
                    out["investment_opinion"] = m2.group(1)
            except Exception as e:
                out["error_step2"] = str(e)

        _polite_sleep()
        return out

    def estimates(self, ticker: str) -> pd.DataFrame:
        """추정 실적 테이블 (매출/영업이익/EPS 추정치 포함)."""
        url = self.BASE.format(code=ticker)
        try:
            tables = pd.read_html(url, encoding="euc-kr")
            for t in tables:
                if "매출액" in str(t):
                    _polite_sleep()
                    return t
        except Exception:
            pass
        _polite_sleep()
        return pd.DataFrame()


# ============================================================
# 4. FnGuide (비공식 크롤링)
# ============================================================
class FnGuideSource:
    """컴퍼니가이드. 네이버보다 재무 데이터 정밀도 높음."""

    SNAPSHOT = "http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{code}"
    FINANCE = "http://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?gicode=A{code}"
    RATIO = "http://comp.fnguide.com/SVO2/ASP/SVD_FinanceRatio.asp?gicode=A{code}"

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._sess = session or _make_session()

    def _fetch_tables(self, url: str) -> list[pd.DataFrame]:
        r = self._sess.get(url, timeout=10)
        r.encoding = "utf-8"
        try:
            return pd.read_html(r.text)
        finally:
            _polite_sleep()

    def snapshot(self, ticker: str) -> list[pd.DataFrame]:
        """기업 개요 + 주요 투자지표 + 컨센서스 테이블 묶음."""
        try:
            return self._fetch_tables(self.SNAPSHOT.format(code=ticker))
        except Exception:
            return []

    def financials(self, ticker: str) -> dict:
        """재무제표. 인덱스 위치는 FnGuide 레이아웃에 따라 변동 가능."""
        try:
            tables = self._fetch_tables(self.FINANCE.format(code=ticker))
        except Exception as e:
            return {"error": str(e)}

        def safe_get(idx: int) -> Optional[pd.DataFrame]:
            return tables[idx] if idx < len(tables) else None

        return {
            "income_annual":      safe_get(0),
            "income_quarterly":   safe_get(1),
            "balance_annual":     safe_get(2),
            "balance_quarterly":  safe_get(3),
            "cashflow_annual":    safe_get(4),
            "cashflow_quarterly": safe_get(5),
        }

    def ratios(self, ticker: str) -> list[pd.DataFrame]:
        """재무비율 (안정성/수익성/성장성/활동성)."""
        try:
            return self._fetch_tables(self.RATIO.format(code=ticker))
        except Exception:
            return []


# ============================================================
# 5. FRED (미국 거시지표)
# ============================================================
class FREDSource:
    """한국 시장도 미국 금리/달러/VIX에 강하게 연동됨."""

    SERIES = {
        "us_10y": "DGS10",          # 미 10년물 국채금리
        "us_2y": "DGS2",            # 미 2년물
        "us_3m": "DGS3MO",          # 미 3개월
        "vix": "VIXCLS",            # 변동성 지수
        "wti": "DCOILWTICO",        # WTI 유가
        "dxy": "DTWEXBGS",          # 달러 인덱스
        "usd_krw": "DEXKOUS",       # 원/달러 환율
        "fed_rate": "FEDFUNDS",     # 연방기금금리
        "cpi": "CPIAUCSL",          # 미국 CPI
    }

    def __init__(self, api_key: Optional[str] = None) -> None:
        from fredapi import Fred
        key = api_key or os.environ.get("FRED_API_KEY")
        if not key:
            raise RuntimeError("FRED_API_KEY 환경변수가 없습니다.")
        self._fred = Fred(api_key=key)

    def series(self, name_or_id: str, start: Optional[str] = None) -> pd.Series:
        sid = self.SERIES.get(name_or_id, name_or_id)
        return self._fred.get_series(sid, observation_start=start)

    def macro_panel(self, start: str = "2020-01-01") -> pd.DataFrame:
        """주요 거시지표를 한 데이터프레임으로."""
        df = pd.DataFrame()
        for name, sid in self.SERIES.items():
            try:
                df[name] = self._fred.get_series(sid, observation_start=start)
            except Exception:
                pass
        return df.ffill()


# ============================================================
# 통합 파사드 + parquet 캐시
# ============================================================
class KoreaStockData:
    """5개 소스를 한 객체로. 캐싱은 parquet 파일."""

    def __init__(self, cache_dir: str = "./cache") -> None:
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True, parents=True)

        self._session = _make_session()
        self.krx = KRXSource()
        self.fdr = FDRSource()
        self.naver = NaverFinanceSource(self._session)
        self.fnguide = FnGuideSource(self._session)
        try:
            self.fred: Optional[FREDSource] = FREDSource()
        except Exception:
            self.fred = None  # API 키 없으면 None

    def cached(self, key: str, fetcher, *, ttl_hours: int = 24) -> pd.DataFrame:
        """간단한 파일 캐시. 같은 key는 ttl 내에서는 재사용.
        key는 파일명에 들어가니 영문/숫자/언더스코어만 쓰세요.
        pickle 사용 (pyarrow 의존성 없음)."""
        path = self.cache / f"{key}.pkl"
        if path.exists():
            age_h = (time.time() - path.stat().st_mtime) / 3600
            if age_h < ttl_hours:
                return pd.read_pickle(path)
        df = fetcher()
        if isinstance(df, pd.DataFrame) and not df.empty:
            df.to_pickle(path)
        return df


# ============================================================
# 사용 예시
# ============================================================
if __name__ == "__main__":
    data = KoreaStockData()

    today = datetime.now().strftime("%Y%m%d")
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    samsung = "005930"

    print("[1] 삼성전자 OHLCV")
    print(data.krx.ohlcv(samsung, one_year_ago, today).tail(), "\n")

    print("[2] 삼성전자 PER/PBR/배당수익률")
    print(data.krx.valuation(samsung, one_year_ago, today).tail(), "\n")

    print("[3] 외국인/기관/개인 순매수")
    print(data.krx.investor_flow(samsung, one_year_ago, today).tail(), "\n")

    print("[4] 공매도 잔고")
    print(data.krx.short_balance(samsung, one_year_ago, today).tail(), "\n")

    print("[5] 전체 종목 리스트 (KRX, 메타 포함)")
    print(data.fdr.listing("KRX").head(), "\n")

    print("[6] 네이버 금융 컨센서스")
    print(data.naver.consensus(samsung), "\n")

    print("[7] FnGuide 재무제표 키")
    fin = data.fnguide.financials(samsung)
    print(list(fin.keys()), "\n")

    if data.fred:
        print("[8] 거시지표 패널")
        print(data.fred.macro_panel(start="2024-01-01").tail())
    else:
        print("[8] FRED_API_KEY 미설정 - 스킵")