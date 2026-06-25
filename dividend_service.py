"""dividend_service.py — 배당 수집 서비스 (KIS 국내 + yfinance 해외).

설계문서(배당캘린더_설계문서.md) 5장 기준. 세 부분으로 구성된다.

    KISClient              토큰 발급·캐싱, 잔고조회(보유종목 자동 수집),
                           국내 배당일정(예탁원정보) 조회
    fetch_dividend_us()    yfinance 로 해외 배당 이력 + 예정 배당 조회
    DividendService        보유종목(자동+수동) × 배당금 → 예상 수령액 계산

이 모듈은 **순수 조회·계산만** 담당한다(설계문서 8장). DB 저장은 호출측
(routes/dividend.py 등 기존 DB 레이어)에서 처리한다.

자체 점검:
    d:/expense_tracker/.venv64/Scripts/python.exe dividend_service.py
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── KIS 도메인 / tr_id (실전 vs 모의) ───────────────────────────────────────
# KIS_ENV=real(기본) 또는 paper. 앱키 36자는 실전 계좌 규격.
_KIS_ENV = os.getenv("KIS_ENV", "real").lower()
if _KIS_ENV == "paper":
    KIS_DOMAIN = "https://openapivts.koreainvestment.com:29443"
    TR_BALANCE = "VTTC8434R"      # 주식잔고조회 (모의)
else:
    KIS_DOMAIN = "https://openapi.koreainvestment.com:9443"
    TR_BALANCE = "TTTC8434R"      # 주식잔고조회 (실전)

TR_DIVIDEND = "HHKDB669102C0"     # 예탁원정보(배당일정) — 실전/모의 공통

_TOKEN_CACHE = Path(__file__).resolve().parent / "cache" / "kis_token.json"


# ─────────────────────────────────────────────────────────────────────────────
# 배당 1건 표준 레코드
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class DividendRow:
    symbol: str
    market: str                       # 'KR' | 'US'
    stock_name: str
    record_date: Optional[str]        # YYYY-MM-DD | None
    pay_date: Optional[str]           # YYYY-MM-DD | None
    dividend_per_share: float
    quantity: float
    expected_amount: float
    currency: str                     # 'KRW' | 'USD'
    status: str                       # 'estimated' | 'confirmed'
    source: str                       # 'kis' | 'yfinance' | 'manual'

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# KISClient — 토큰 / 잔고 / 국내 배당일정
# ─────────────────────────────────────────────────────────────────────────────
class KISClient:
    """한국투자증권 Open API 클라이언트.

    토큰은 발급 후 24시간 유효하며 분당 발급 횟수 제한이 있으므로 파일에 캐싱한다.
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        account_no: Optional[str] = None,
        timeout: int = 10,
    ):
        self.app_key = app_key or os.getenv("KIS_APP_KEY", "")
        self.app_secret = app_secret or os.getenv("KIS_APP_SECRET", "")
        account_no = account_no or os.getenv("KIS_ACCOUNT_NO", "")
        if not (self.app_key and self.app_secret):
            raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 가 설정되지 않았습니다 (.env 확인).")

        # '68925608-01' → CANO='68925608', ACNT_PRDT_CD='01'
        if "-" in account_no:
            self.cano, self.acnt_prdt_cd = account_no.split("-", 1)
        else:
            self.cano, self.acnt_prdt_cd = account_no[:8], (account_no[8:] or "01")

        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expire: float = 0.0

    # ── 토큰 ────────────────────────────────────────────────────────────────
    def _load_cached_token(self) -> bool:
        try:
            data = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if data.get("app_key") != self.app_key:
            return False
        if data.get("expire", 0) <= time.time() + 60:
            return False
        self._token = data.get("access_token")
        self._token_expire = data.get("expire", 0)
        return bool(self._token)

    def _save_cached_token(self) -> None:
        try:
            _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _TOKEN_CACHE.write_text(json.dumps({
                "app_key": self.app_key,
                "access_token": self._token,
                "expire": self._token_expire,
            }), encoding="utf-8")
        except OSError as e:
            logger.warning("[KIS] 토큰 캐시 저장 실패: %s", e)

    def get_token(self) -> str:
        """유효 토큰 반환(메모리 → 파일 캐시 → 신규 발급)."""
        if self._token and self._token_expire > time.time() + 60:
            return self._token
        if self._load_cached_token():
            return self._token

        url = f"{KIS_DOMAIN}/oauth2/tokenP"
        resp = requests.post(url, json={
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"[KIS] 토큰 발급 실패: {data}")
        self._token = token
        # expires_in(초) 기준, 없으면 23시간 보수적 적용
        self._token_expire = time.time() + int(data.get("expires_in", 23 * 3600))
        self._save_cached_token()
        logger.info("[KIS] 신규 토큰 발급 완료")
        return token

    def _headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    # ── 잔고조회 (보유종목 자동 수집) ─────────────────────────────────────────
    def get_balance(self) -> list[dict]:
        """주식 잔고조회 → [{'code','name','quantity','avg_price'}, ...]"""
        url = f"{KIS_DOMAIN}/uapi/domestic-stock/v1/trading/inquire-balance"
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        resp = requests.get(url, headers=self._headers(TR_BALANCE),
                            params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("rt_cd") != "0":
            raise RuntimeError(f"[KIS] 잔고조회 실패: {data.get('msg1')} ({data.get('msg_cd')})")

        holdings = []
        for it in data.get("output1", []) or []:
            qty = _to_float(it.get("hldg_qty"))
            code = (it.get("pdno") or "").strip()
            if qty > 0 and code:
                holdings.append({
                    "code": code.zfill(6),
                    "name": (it.get("prdt_name") or code).strip(),
                    "quantity": qty,
                    "avg_price": _to_float(it.get("pchs_avg_pric")),
                })
        return holdings

    # ── 국내 배당일정 (예탁원정보) ────────────────────────────────────────────
    # ⚠️ 설계문서 5장 경고: 본 엔드포인트/필드명은 계정·문서 버전에 따라 다를 수
    #    있다. 응답을 방어적으로 파싱하고, 핵심 필드가 없으면 graceful skip 한다.
    def fetch_dividend_kr(
        self,
        symbol: str = "",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        """국내 배당일정 조회.

        symbol="" 이면 기간 전체, 지정 시 해당 종목만.
        반환: [{'symbol','stock_name','record_date','pay_date','dps'}, ...]
        날짜는 YYYY-MM-DD.
        """
        today = datetime.now()
        f_dt = from_date or (today - timedelta(days=180)).strftime("%Y%m%d")
        t_dt = to_date or (today + timedelta(days=180)).strftime("%Y%m%d")

        url = f"{KIS_DOMAIN}/uapi/domestic-stock/v1/ksdinfo/dividend"
        params = {
            "CTS": "",
            "GB1": "0",           # 0: 배당락 기준 조회
            "F_DT": f_dt,
            "T_DT": t_dt,
            "SHT_CD": symbol.strip(),
            "HIGH_GB": "",
        }
        resp = requests.get(url, headers=self._headers(TR_DIVIDEND),
                            params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("rt_cd") not in ("0", None):
            logger.warning("[KIS] 배당일정 조회 경고: %s (%s)",
                           data.get("msg1"), data.get("msg_cd"))

        rows = []
        out = data.get("output1") or data.get("output") or []
        if isinstance(out, dict):
            out = [out]
        for it in out:
            dps = _to_float(it.get("per_sto_divi_amt") or it.get("divi_amt"))
            sym = (it.get("sht_cd") or it.get("pdno") or symbol or "").strip()
            if not sym or dps <= 0:
                continue
            rows.append({
                "symbol": sym.zfill(6),
                "stock_name": (it.get("isin_name") or it.get("prdt_name") or "").strip(),
                "record_date": _kis_date(it.get("record_date") or it.get("bas_dt")),
                "pay_date": _kis_date(it.get("divi_pay_dt") or it.get("dvdn_pay_dt")),
                "dps": dps,
            })
        return rows


# ─────────────────────────────────────────────────────────────────────────────
# 해외 배당 (yfinance)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_dividend_us(symbol: str) -> list[dict]:
    """yfinance 로 해외 배당 이력 + 다음 예정 배당(추정) 조회.

    반환: [{'pay_date','dps','status'}, ...]  (날짜 YYYY-MM-DD)
    이력은 confirmed, 추정 다음 배당은 estimated.
    """
    out: list[dict] = []
    try:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        divs = tk.dividends
        if divs is None or len(divs) == 0:
            return out

        history = [(dt.to_pydatetime().replace(tzinfo=None), float(amt))
                   for dt, amt in divs.items()]
        now = datetime.now()
        one_year_ago = now - timedelta(days=365)
        for dt, amt in history:
            if dt < one_year_ago - timedelta(days=400):
                continue
            out.append({
                "pay_date": dt.strftime("%Y-%m-%d"),
                "dps": round(amt, 4),
                "status": "confirmed",
            })

        # 다음 배당 추정: 최근 배당 간격 중앙값 + 마지막 배당락
        if len(history) >= 2:
            gaps = sorted((history[i][0] - history[i - 1][0]).days
                          for i in range(max(1, len(history) - 6), len(history)))
            median_gap = gaps[len(gaps) // 2]
            next_dt = history[-1][0] + timedelta(days=median_gap)
            if next_dt > now:
                out.append({
                    "pay_date": next_dt.strftime("%Y-%m-%d"),
                    "dps": round(history[-1][1], 4),
                    "status": "estimated",
                })
    except Exception as e:
        logger.warning("[yfinance] %s 배당 조회 실패: %s", symbol, e)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# DividendService — 보유종목 × 배당금 → 예상 수령액
# ─────────────────────────────────────────────────────────────────────────────
class DividendService:
    """배당 수집·계산 오케스트레이터.

    collect() 는 DividendRow 리스트를 반환할 뿐 DB 저장은 하지 않는다.
    """

    def __init__(self, kis: Optional[KISClient] = None):
        self.kis = kis

    def collect(
        self,
        manual_holdings: Optional[list[dict]] = None,
        kr_schedule_lookup: bool = True,
    ) -> list[DividendRow]:
        """보유종목(KIS 자동 + 수동) 의 배당을 수집·계산.

        manual_holdings: [{'code','name','quantity','market'?('KR'|'US')}, ...]
            market 미지정 시 6자리 숫자=KR, 그 외=US 로 판정.
        반환: DividendRow 리스트 (예상/확정 혼합).
        """
        holdings = self._merge_holdings(manual_holdings)
        rows: list[DividendRow] = []

        # 국내 배당일정은 종목 무관 전체를 한 번에 받아 캐싱(호출 최소화)
        kr_sched: dict[str, list[dict]] = {}
        if kr_schedule_lookup and self.kis and any(h["market"] == "KR" for h in holdings):
            try:
                for s in self.kis.fetch_dividend_kr():
                    kr_sched.setdefault(s["symbol"], []).append(s)
            except Exception as e:
                logger.warning("[collect] KIS 배당일정 조회 실패, yfinance 폴백: %s", e)

        for h in holdings:
            if h["market"] == "KR":
                rows.extend(self._collect_kr(h, kr_sched.get(h["code"])))
            else:
                rows.extend(self._collect_us(h))
        return rows

    # ── 내부 ──────────────────────────────────────────────────────────────────
    def _merge_holdings(self, manual: Optional[list[dict]]) -> list[dict]:
        merged: dict[str, dict] = {}
        # KIS 자동
        if self.kis:
            try:
                for h in self.kis.get_balance():
                    merged[h["code"]] = {**h, "market": "KR", "source": "kis"}
            except Exception as e:
                logger.warning("[collect] KIS 잔고조회 실패: %s", e)
        # 수동 (자동분을 덮어쓰지 않음 — KIS 우선)
        for h in manual or []:
            code = str(h.get("code", "")).strip()
            if not code:
                continue
            market = h.get("market") or ("KR" if code.isdigit() and len(code) <= 6 else "US")
            code = code.zfill(6) if market == "KR" else code.upper()
            if code in merged:
                continue
            merged[code] = {
                "code": code,
                "name": h.get("name") or code,
                "quantity": _to_float(h.get("quantity")),
                "market": market,
                "source": "manual",
            }
        return [h for h in merged.values() if h["quantity"] > 0]

    def _collect_kr(self, h: dict, sched: Optional[list[dict]]) -> list[DividendRow]:
        qty = h["quantity"]
        rows: list[DividendRow] = []
        if sched:
            for s in sched:
                dps = s["dps"]
                rows.append(DividendRow(
                    symbol=h["code"], market="KR", stock_name=s["stock_name"] or h["name"],
                    record_date=s["record_date"], pay_date=s["pay_date"],
                    dividend_per_share=dps, quantity=qty,
                    expected_amount=round(dps * qty, 2),
                    currency="KRW", status="confirmed", source="kis",
                ))
            return rows
        # KIS 일정이 없으면 yfinance 로 추정 (.KS → .KQ)
        for suffix in (".KS", ".KQ"):
            us = fetch_dividend_us(h["code"] + suffix)
            if us:
                for d in us:
                    rows.append(DividendRow(
                        symbol=h["code"], market="KR", stock_name=h["name"],
                        record_date=None, pay_date=d["pay_date"],
                        dividend_per_share=d["dps"], quantity=qty,
                        expected_amount=round(d["dps"] * qty, 2),
                        currency="KRW", status="estimated", source="yfinance",
                    ))
                break
        return rows

    def _collect_us(self, h: dict) -> list[DividendRow]:
        qty = h["quantity"]
        rows: list[DividendRow] = []
        for d in fetch_dividend_us(h["code"]):
            rows.append(DividendRow(
                symbol=h["code"], market="US", stock_name=h["name"],
                record_date=None, pay_date=d["pay_date"],
                dividend_per_share=d["dps"], quantity=qty,
                expected_amount=round(d["dps"] * qty, 2),
                currency="USD", status=d["status"], source="yfinance",
            ))
        return rows


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _kis_date(v) -> Optional[str]:
    """KIS 날짜 → YYYY-MM-DD. 'YYYYMMDD'·'YYYY/MM/DD'·'YYYY-MM-DD' 혼용 대응.
    빈값/0 은 None."""
    digits = "".join(ch for ch in (str(v) if v is not None else "") if ch.isdigit())
    if len(digits) != 8 or digits == "00000000":
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


# ─────────────────────────────────────────────────────────────────────────────
# 자체 점검
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print(f"== KIS 환경: {_KIS_ENV} ({KIS_DOMAIN}) ==")
    try:
        kis = KISClient()
        print(f"  계좌: CANO={kis.cano}, PRDT={kis.acnt_prdt_cd}")
    except Exception as e:
        print(f"[FAIL] KISClient 초기화: {e}")
        sys.exit(1)

    # 1) 토큰
    try:
        tok = kis.get_token()
        print(f"[OK] 토큰 발급: {tok[:12]}...")
    except Exception as e:
        print(f"[FAIL] 토큰 발급: {e}")
        kis = None

    # 2) 잔고조회
    balance = []
    if kis:
        try:
            balance = kis.get_balance()
            print(f"[OK] 잔고조회: {len(balance)}종목 " +
                  ", ".join(f"{h['name']}({h['code']})x{h['quantity']:g}" for h in balance[:5]))
        except Exception as e:
            print(f"[WARN] 잔고조회: {e}")

    # 3) 국내 배당일정 (보유 첫 종목 또는 삼성전자)
    if kis:
        probe = balance[0]["code"] if balance else "005930"
        try:
            sched = kis.fetch_dividend_kr(symbol=probe)
            print(f"[OK] 배당일정({probe}): {len(sched)}건 {sched[:2]}")
        except Exception as e:
            print(f"[WARN] 배당일정: {e}")

    # 4) yfinance 해외
    try:
        us = fetch_dividend_us("AAPL")
        print(f"[OK] yfinance(AAPL): {len(us)}건 {us[-2:]}")
    except Exception as e:
        print(f"[WARN] yfinance: {e}")

    # 5) 전체 collect (수동 보유 샘플 포함)
    svc = DividendService(kis=kis)
    rows = svc.collect(manual_holdings=[
        {"code": "AAPL", "name": "Apple", "quantity": 10, "market": "US"},
    ])
    print(f"[OK] collect(): {len(rows)}건")
    for r in rows[:8]:
        print("   ", r.to_dict())
