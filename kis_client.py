"""
kis_client.py — 한국투자증권(KIS) OpenAPI REST 시장데이터 클라이언트.

배포(클라우드/리눅스) 환경에서도 동작하도록, 시세·일봉 같은 '공용 시장 데이터'를
32비트 키움 OCX 콜렉터 대신 KIS REST 로 조회한다. 키움 콜렉터는 집 PC(Windows)에서만
돌고 단일 계정에 묶여 있어 다중 유저 공개 배포에 부적합하기 때문이다.

⚠ 이 클라이언트는 '읽기 전용' 시장 데이터만 제공한다. 주문(매수/매도) 메서드는
   의도적으로 두지 않는다 — 주문 대행(투자일임)은 영구 금지(trading/trader.py 참고).

반환 형식은 키움 콜렉터(_parse_price_data) 및 KiwoomClient.get_ohlcv 와 동일하게 맞춰
호출부가 코드 변경 없이 그대로 동작하게 한다.
"""
import os
import time
import threading
import logging
from datetime import datetime, timedelta

import requests
import pandas as pd

logger = logging.getLogger(__name__)

KIS_BASE        = "https://openapi.koreainvestment.com:9443"
KIS_APP_KEY     = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET  = os.getenv("KIS_APP_SECRET", "")

_PRICE_TTL = 5.0   # 초 — 동일 종목 연속 조회 시 REST 호출 절감


def _safe_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


def _safe_float(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


class KISClient:
    """KIS REST 시장 데이터 싱글톤. enabled() 가 False면 호출부는 키움 콜렉터로 폴백."""

    def __init__(self):
        self._token: str | None = None
        self._token_exp: float = 0.0          # epoch 초
        self._token_lock = threading.Lock()
        self._price_cache: dict[str, dict] = {}   # code -> {"data":..., "ts":...}
        self._cache_lock = threading.Lock()

    # ── 가용성 ────────────────────────────────────────────────
    def enabled(self) -> bool:
        return bool(KIS_APP_KEY and KIS_APP_SECRET)

    # ── 토큰 ──────────────────────────────────────────────────
    def _get_token(self) -> str | None:
        if not self.enabled():
            return None
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        with self._token_lock:
            now = time.time()
            if self._token and now < self._token_exp - 60:
                return self._token
            try:
                res = requests.post(
                    f"{KIS_BASE}/oauth2/tokenP",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": KIS_APP_KEY,
                        "appsecret": KIS_APP_SECRET,
                    },
                    timeout=5,
                )
                res.raise_for_status()
                data = res.json()
                self._token = data["access_token"]
                # expires_in(초) 우선, 없으면 23시간으로 보수 설정
                self._token_exp = time.time() + int(data.get("expires_in", 82800))
                return self._token
            except Exception as e:
                logger.error(f"[KIS] 토큰 발급 실패: {e}")
                return None

    def _headers(self, tr_id: str) -> dict | None:
        token = self._get_token()
        if not token:
            return None
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": tr_id,
            "custtype": "P",
        }

    # ── 현재가 / 재무 ─────────────────────────────────────────
    def get_stock_price(self, code: str) -> dict | None:
        """현재가+재무 단건 조회. 키움 _parse_price_data 와 동일한 키 구조로 반환."""
        with self._cache_lock:
            c = self._price_cache.get(code)
            if c and time.time() - c["ts"] < _PRICE_TTL:
                return c["data"]

        headers = self._headers("FHKST01010100")
        if headers is None:
            return None
        try:
            res = requests.get(
                f"{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-price",
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
                headers=headers, timeout=5,
            )
            res.raise_for_status()
            body = res.json()
            o = body.get("output") or {}
            if not o or not o.get("stck_prpr"):
                return None

            change = _safe_int(o.get("prdy_vrss", 0))
            if str(o.get("prdy_vrss_sign", "")) in ("4", "5"):   # 하한/하락
                change = -abs(change)
            else:
                change = abs(change)

            data = {
                "code":          code,
                # inquire-price 는 종목명을 주지 않는다(rprs_mrkt_kor_name=시장명).
                # 키움 콜렉터 관례대로 종목명 미상 시 코드로 폴백한다.
                "name":          code,
                "price":         _safe_int(o.get("stck_prpr", 0)),
                "base_price":    _safe_int(o.get("stck_sdpr", 0)),     # 전일종가(기준가)
                "change":        change,
                "rate":          _safe_float(o.get("prdy_ctrt", 0)),
                "volume":        _safe_int(o.get("acml_vol", 0)),
                "trade_amount":  _safe_int(o.get("acml_tr_pbmn", 0)),
                "open":          _safe_int(o.get("stck_oprc", 0)),
                "high":          _safe_int(o.get("stck_hgpr", 0)),
                "low":           _safe_int(o.get("stck_lwpr", 0)),
                "market_cap":    _safe_int(o.get("hts_avls", 0)),      # 억원
                "per":           _safe_float(o.get("per", 0)),
                "pbr":           _safe_float(o.get("pbr", 0)),
                "eps":           _safe_int(o.get("eps", 0)),
                "bps":           _safe_int(o.get("bps", 0)),
                "roe":           0.0,                                  # inquire-price 미제공
                "dividend":      0.0,                                  # inquire-price 미제공
                "week52_high":   _safe_int(o.get("w52_hgpr", 0)),
                "week52_low":    _safe_int(o.get("w52_lwpr", 0)),
                "foreign_ratio": _safe_float(o.get("hts_frgn_ehrt", 0)),
                "shares":        _safe_int(o.get("lstn_stcn", 0)),
                "price_source":  "KIS",
            }
            with self._cache_lock:
                self._price_cache[code] = {"data": data, "ts": time.time()}
            return data
        except Exception as e:
            logger.warning(f"[KIS] 현재가 조회 실패 ({code}): {e}")
            return None

    def get_best_price(self, code: str) -> dict | None:
        """세션 무관 현재가. 키움 get_best_price 자리 대체(호가 세션 정보는 생략)."""
        return self.get_stock_price(code)

    def get_stock_info(self, code: str) -> dict | None:
        return self.get_stock_price(code)

    def get_foreign_hold_ratio(self, code: str) -> float:
        info = self.get_stock_price(code)
        return info.get("foreign_ratio", 0.0) if info else 0.0

    # ── 일봉 OHLCV ────────────────────────────────────────────
    def get_ohlcv(self, code: str, count: int = 80) -> pd.DataFrame:
        """
        일봉 차트 조회. 키움 KiwoomClient.get_ohlcv 와 동일하게
        DatetimeIndex + ['open','high','low','close','volume'] (오름차순) 반환.
        실패 시 빈 DataFrame.

        KIS inquire-daily-itemchartprice 는 1회 호출당 최대 100행(최근→과거)이라,
        count>100 이면 날짜창을 과거로 옮기며 페이지네이션한다.
        """
        headers = self._headers("FHKST03010100")
        if headers is None:
            return pd.DataFrame()

        collected: dict[str, dict] = {}   # YYYYMMDD -> row
        end = datetime.now()
        max_pages = max(1, (count // 100) + 2)
        try:
            for _ in range(max_pages):
                start = end - timedelta(days=150)   # ≈ 100 영업일 여유
                res = requests.get(
                    f"{KIS_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                    params={
                        "FID_COND_MRKT_DIV_CODE": "J",
                        "FID_INPUT_ISCD": code,
                        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                        "FID_PERIOD_DIV_CODE": "D",
                        "FID_ORG_ADJ_PRC": "0",
                    },
                    headers=headers, timeout=7,
                )
                res.raise_for_status()
                rows = res.json().get("output2") or []
                rows = [r for r in rows if r.get("stck_bsop_date")]
                if not rows:
                    break
                for r in rows:
                    collected[r["stck_bsop_date"]] = r
                if len(collected) >= count:
                    break
                oldest = min(r["stck_bsop_date"] for r in rows)
                nxt = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
                if nxt >= end:    # 진전 없음 → 무한루프 방지
                    break
                end = nxt

            if not collected:
                return pd.DataFrame()

            df = pd.DataFrame([
                {
                    "date":   d,
                    "open":   _safe_int(r.get("stck_oprc", 0)),
                    "high":   _safe_int(r.get("stck_hgpr", 0)),
                    "low":    _safe_int(r.get("stck_lwpr", 0)),
                    "close":  _safe_int(r.get("stck_clpr", 0)),
                    "volume": _safe_int(r.get("acml_vol", 0)),
                }
                for d, r in collected.items()
            ])
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
            df = df.dropna(subset=["date"]).set_index("date").sort_index()
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            return df.tail(count)
        except Exception as e:
            logger.warning(f"[KIS] OHLCV 조회 실패 ({code}): {e}")
            return pd.DataFrame()


# 싱글톤
kis = KISClient()
