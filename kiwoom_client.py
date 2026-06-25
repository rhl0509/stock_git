import requests
import pandas as pd
from config import Config

class KiwoomClient:
    """
    64비트 메인 서버에서 32비트 콜렉터(포트 5100)로 HTTP 요청을 보내는 클라이언트
    기존 KiwoomWorker와 인터페이스를 동일하게 유지하여 코드 변경 최소화
    """
    BASE_URL = f"http://127.0.0.1:{Config.KIWOOM_COLLECTOR_PORT}"

    def __init__(self):
        self._theme_index_cache = None

    def get_login_state(self) -> int:
        try:
            r = requests.get(f"{self.BASE_URL}/status", timeout=3)
            return r.json().get('state', 0)
        except Exception:
            return 0

    def login(self, timeout=60) -> dict:
        try:
            r = requests.post(f"{self.BASE_URL}/login", timeout=timeout)
            data = r.json()
            if not data.get('success'):
                print(f"[KiwoomClient] 로그인 실패: err_code={data.get('err_code')} — {data.get('msg')}")
            return data
        except Exception as e:
            msg = str(e)
            print(f"[KiwoomClient] 로그인 호출 실패: {msg}")
            return {"success": False, "msg": f"32비트 콜렉터 연결 실패: {msg}"}

    def get_stock_price(self, code: str, timeout=5) -> dict | None:
        try:
            r = requests.get(f"{self.BASE_URL}/price/{code}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_nxt_price(self, code: str, timeout=5) -> dict | None:
        try:
            r = requests.get(f"{self.BASE_URL}/nxt/price/{code}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_best_price(self, code: str, timeout=5) -> dict | None:
        try:
            r = requests.get(f"{self.BASE_URL}/best/price/{code}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_stock_info(self, code: str, timeout=5) -> dict | None:
        try:
            r = requests.get(f"{self.BASE_URL}/info/{code}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_account_no(self) -> str | None:
        try:
            r = requests.get(f"{self.BASE_URL}/account/no", timeout=3)
            if r.status_code == 200:
                return r.json().get('account_no')
            return None
        except Exception:
            return None

    def get_account_holdings(self, timeout=10) -> list | None:
        try:
            r = requests.get(f"{self.BASE_URL}/account/holdings", timeout=timeout)
            if r.status_code == 200:
                return r.json().get('holdings')
            return None
        except Exception:
            return None

    def get_account_full(self, timeout=10) -> dict | None:
        """holdings + deposit 전체 응답 반환"""
        try:
            r = requests.get(f"{self.BASE_URL}/account/holdings", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_realized_pnl(self, date_from: str, date_to: str, timeout=20) -> dict | None:
        """계좌별 실현손익 조회 (opt10073). date: YYYYMMDD"""
        try:
            r = requests.get(
                f"{self.BASE_URL}/account/realized-pnl",
                params={"from": date_from, "to": date_to},
                timeout=timeout,
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_period_trades(self, date_from: str, date_to: str, timeout=20) -> list | None:
        """기간별 체결 내역 조회 (opw00015). date: YYYYMMDD"""
        try:
            r = requests.get(
                f"{self.BASE_URL}/account/period-trades",
                params={"from": date_from, "to": date_to},
                timeout=timeout,
            )
            if r.status_code == 200:
                return r.json().get('trades')
            return None
        except Exception:
            return None

    def get_kiwoom_daily_trades(self, timeout=15) -> list | None:
        """키움 당일 체결현황 조회 (opw00007)"""
        try:
            r = requests.get(f"{self.BASE_URL}/account/trades", timeout=timeout)
            if r.status_code == 200:
                return r.json().get('trades')
            return None
        except Exception:
            return None

    def get_deposit(self, timeout=5) -> int | None:
        try:
            r = requests.get(f"{self.BASE_URL}/account/deposit", timeout=timeout)
            if r.status_code == 200:
                return r.json().get('deposit')
            return None
        except Exception:
            return None

    def get_investor_trend(self, code: str, investor_type: str = "외국인", count: int = 20, timeout=10) -> list | None:
        try:
            r = requests.get(f"{self.BASE_URL}/investor/{code}?type={investor_type}&count={count}", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_foreign_hold_ratio(self, code: str) -> float:
        info = self.get_stock_info(code)
        if info:
            return info.get("foreign_ratio", 0.0)
        return 0.0

    def get_futures_price(self, code: str | None = None, timeout=5) -> dict | None:
        """KOSPI200 선물 현재가·등락율. code 미지정 시 콜렉터가 최근월물 자동 선택."""
        try:
            params = {"code": code} if code else {}
            r = requests.get(f"{self.BASE_URL}/futures/price", params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def get_kospi200_front_code(self, timeout=5) -> str | None:
        try:
            r = requests.get(f"{self.BASE_URL}/futures/code", timeout=timeout)
            if r.status_code == 200:
                return r.json().get("code")
            return None
        except Exception:
            return None

    def get_ohlcv(self, code: str, count: int = 80, timeout=10) -> pd.DataFrame | None:
        try:
            r = requests.get(f"{self.BASE_URL}/ohlcv/{code}?count={count}", timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    return None
                df = pd.DataFrame(data)
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                return df
            return None
        except Exception as e:
            print(f"[KiwoomClient] OHLCV 조회 실패: {e}")
            return None

    def load_condition_list(self, timeout=10) -> dict:
        try:
            r = requests.get(f"{self.BASE_URL}/conditions", timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            return {}

    def run_condition(self, condition_name: str, timeout=15) -> list:
        try:
            r = requests.post(f"{self.BASE_URL}/condition/run", json={"name": condition_name}, timeout=timeout)
            if r.status_code == 200:
                return r.json().get('stocks', [])
            return []
        except Exception:
            return []

    def get_theme_list(self, sort: int = 0) -> list:
        try:
            r = requests.get(f"{self.BASE_URL}/themes?sort={sort}", timeout=5)
            if r.status_code == 200:
                return r.json()
            return []
        except Exception:
            return []

    def get_theme_stocks(self, theme_code: str) -> list:
        try:
            r = requests.post(f"{self.BASE_URL}/theme/stocks", json={"theme_code": theme_code}, timeout=5)
            if r.status_code == 200:
                return r.json()
            return []
        except Exception:
            return []

    def build_theme_index(self, force=False) -> dict:
        try:
            r = requests.post(f"{self.BASE_URL}/theme-index/build", timeout=30)
            if r.status_code == 200:
                data = r.json()
                self._theme_index_cache = {"built": True, "count": data.get("count", 0)}
            return {}
        except Exception:
            return {}

    def get_related_stocks(self, code: str, force: bool = False) -> dict:
        try:
            r = requests.post(f"{self.BASE_URL}/related-stocks",
                              json={"code": code, "force": force}, timeout=60)
            if r.status_code == 200:
                return r.json()
            return {"error": r.json().get("error", "오류")}
        except Exception as e:
            return {"error": str(e)}

def fetch_market_session() -> dict:
    try:
        r = requests.get(f"http://127.0.0.1:{Config.KIWOOM_COLLECTOR_PORT}/session", timeout=2)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    
    return {
        "session": "CLOSED",
        "label": "연결 실패 (장 마감 처리)",
        "krx": False,
        "nxt": False,
        "price_source": "NONE",
        "note": "32비트 콜렉터 서버에 연결할 수 없습니다."
    }

# 기존 kiwoom 객체를 대체할 싱글톤
kiwoom = KiwoomClient()
