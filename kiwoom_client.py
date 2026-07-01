"""kiwoom_client.py — 시장데이터 파사드 (KIS REST 전용).

과거엔 32비트 키움 OpenAPI+ 콜렉터(포트 5100)로 프록시했으나, 배포(클라우드/리눅스)
에서는 콜렉터를 띄울 수 없어 **KIS REST 전용**으로 전환했다. 시세·호가·일봉·종목정보·
외국인보유율은 KIS 로 조회한다.

계좌·예수금·실현손익·조건검색·테마·선물 등은 키움 단일계좌(OCX) 전용 기능이라
배포에서 제공하지 않는다. 호출부 호환을 위해 메서드는 남기되 빈 값을 반환한다.
"""
import logging

try:
    from kis_client import kis
except Exception:           # KIS 클라이언트 로드 실패 시에도 앱은 살린다.
    kis = None

logger = logging.getLogger(__name__)


def _kis_on() -> bool:
    return kis is not None and kis.enabled()


class KiwoomClient:
    """시장데이터 파사드. 시세 계열은 KIS REST, 콜렉터 전용 기능은 미지원(빈 값)."""

    def __init__(self):
        self._theme_index_cache = None

    # ── 상태 ──────────────────────────────────────────────
    def market_data_ready(self) -> bool:
        """시세/일봉을 제공할 수 있는 상태인지. KIS 사용 가능하면 True."""
        return _kis_on()

    def get_login_state(self) -> int:
        # 키움 OCX 로그인 개념 제거. 시세는 KIS 로 제공하므로 항상 0(미로그인).
        return 0

    def login(self, timeout=60) -> dict:
        return {"success": False, "msg": "키움 콜렉터는 배포에서 제거되었습니다(KIS 사용)."}

    # ── 시세 / 일봉 (KIS REST) ────────────────────────────
    def get_stock_price(self, code: str, timeout=5) -> dict | None:
        return kis.get_stock_price(code) if _kis_on() else None

    def get_best_price(self, code: str, timeout=5) -> dict | None:
        return kis.get_best_price(code) if _kis_on() else None

    def get_stock_info(self, code: str, timeout=5) -> dict | None:
        return kis.get_stock_info(code) if _kis_on() else None

    def get_ohlcv(self, code: str, count: int = 80, timeout=10):
        if _kis_on():
            df = kis.get_ohlcv(code, count=count)
            if df is not None and not df.empty:
                return df
        return None

    def get_foreign_hold_ratio(self, code: str) -> float:
        info = self.get_stock_info(code)
        return info.get("foreign_ratio", 0.0) if info else 0.0

    # ── 콜렉터 전용(키움 단일계좌) — 배포 미지원, 호출부 호환용 스텁 ──
    def get_nxt_price(self, code: str, timeout=5):
        return None

    def get_account_no(self):
        return None

    def get_account_holdings(self, timeout=10):
        return None

    def get_account_full(self, timeout=10):
        return None

    def get_realized_pnl(self, date_from: str, date_to: str, timeout=20):
        return None

    def get_period_trades(self, date_from: str, date_to: str, timeout=20):
        return None

    def get_kiwoom_daily_trades(self, timeout=15):
        return None

    def get_deposit(self, timeout=5):
        return None

    def get_investor_trend(self, code: str, investor_type: str = "외국인", count: int = 20, timeout=10):
        return None

    def get_futures_price(self, code: str | None = None, timeout=5):
        return None

    def get_kospi200_front_code(self, timeout=5):
        return None

    def load_condition_list(self, timeout=10) -> dict:
        return {}

    def run_condition(self, condition_name: str, timeout=15) -> list:
        return []

    def get_theme_list(self, sort: int = 0) -> list:
        return []

    def get_theme_stocks(self, theme_code: str) -> list:
        return []

    def build_theme_index(self, force=False) -> dict:
        return {}

    def get_related_stocks(self, code: str, force: bool = False) -> dict:
        return {"error": "테마/연관주는 배포에서 미지원(키움 콜렉터 제거)."}


def fetch_market_session() -> dict:
    """장 세션 정보. 키움 콜렉터 제거로 정적 기본값을 반환한다."""
    on = _kis_on()
    return {
        "session": "UNKNOWN",
        "label": "KIS 시세 사용" if on else "시세 소스 없음",
        "krx": on,
        "nxt": False,
        "price_source": "KIS" if on else "NONE",
        "note": "키움 콜렉터 제거됨 — 시세는 KIS REST 사용.",
    }


# 기존 kiwoom 객체를 대체할 싱글톤
kiwoom = KiwoomClient()
