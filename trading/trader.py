"""
trading/trader.py
──────────────────────────────────────────────────────────────────────────────
매매 실행 모듈.

역할:
  1. signal.py 의 BUY/SELL/HOLD 신호 수신
  2. 포지션 사이징 (계좌 잔고 비율 기반)
  3. 키움 API 로 실제 매수/매도 주문 실행
  4. 손절가 / 익절가 자동 관리
  5. 중복 주문 방지 / 포트폴리오 상태 추적

사용 방법 (routes/stock_ml.py 또는 별도 스케줄러에서):
  from trading.trader import Trader
  trader = Trader()
  trader.run_signal(ticker="005930", ticker_name="삼성전자")

주의:
  실제 자금이 투입되는 코드입니다.
  반드시 모의투자 계좌로 먼저 검증 후 실계좌에 적용하세요.
──────────────────────────────────────────────────────────────────────────────
"""

import os
import json
import logging
import threading
import time
from datetime import datetime
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ⛔ 실매매(주문 대행) 영구 차단 — 하드코딩
# ─────────────────────────────────────────────────────────────────────────────
# 이 서비스는 정보 제공(시세·분석·추천)만 한다. 운영자 본인 계좌라도 이 프로세스가
# 사용자 트래픽 위에서 자동으로 실주문을 내보내면 안 된다. 타인 자금을 받아 대신
# 주문하는 행위는 '투자일임업' 인가 대상이라 무인가 시 위법이다.
# 따라서 어떤 환경변수·설정으로도 우회할 수 없게, 실주문 송신 경로를 코드 차원에서
# 영구히 막는다. (env가 아니라 상수 — 운영 중 실수로 켜지는 것 방지)
LIVE_ORDER_EXECUTION_DISABLED = True


# ─────────────────────────────────────────────────────────────────────────────
# 리스크 설정 (환경변수 또는 직접 수정)
# ─────────────────────────────────────────────────────────────────────────────
class RiskConfig:
    """
    매매 리스크 설정.
    운영 전 반드시 검토 후 조정하세요.
    """
    # 종목당 최대 투자 비율 (계좌 잔고 대비)
    MAX_POSITION_RATIO: float = float(os.getenv("MAX_POSITION_RATIO", "0.10"))   # 10%

    # 동시 보유 최대 종목 수
    MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS", "5"))

    # 손절선 (진입가 대비 하락률)
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "-0.03"))            # -3%

    # 익절선 (진입가 대비 상승률)
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.06"))         # +6%

    # 매수 최소 신호 확률 임계값 (signal.py 기준)
    MIN_BUY_PROB: float = float(os.getenv("MIN_BUY_PROB", "0.60"))              # 60%

    # 매도 최소 신호 확률 임계값
    MIN_SELL_PROB: float = float(os.getenv("MIN_SELL_PROB", "0.60"))            # 60%

    # 주문 타입: "시장가" | "지정가"
    ORDER_TYPE: str = os.getenv("ORDER_TYPE", "시장가")

    # 지정가 주문 시 현재가 대비 슬리피지 허용 비율
    SLIPPAGE_PCT: float = float(os.getenv("SLIPPAGE_PCT", "0.001"))             # 0.1%

    # 최소 거래량 필터 (하루 평균 거래량)
    MIN_VOLUME: int = int(os.getenv("MIN_VOLUME", "100000"))

    # 장 마감 n분 전 신규 매수 금지
    NO_BUY_BEFORE_CLOSE_MIN: int = int(os.getenv("NO_BUY_BEFORE_CLOSE_MIN", "30"))


# ─────────────────────────────────────────────────────────────────────────────
# 포지션 데이터 클래스
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Position:
    """
    보유 중인 종목 포지션 정보.
    Trader._positions dict 에 ticker 를 키로 저장.
    """
    ticker:       str
    ticker_name:  str
    quantity:     int        # 보유 수량
    avg_price:    float      # 평균 매입가
    entry_time:   str        # 진입 시각 (ISO 8601)
    stop_price:   float      # 손절가
    target_price: float      # 익절가
    last_signal:  str = "BUY"

    @property
    def current_pnl_pct(self, current_price: float = 0) -> float:
        """현재가 기준 수익률 (current_price 별도 전달 필요)."""
        if self.avg_price == 0:
            return 0.0
        return (current_price - self.avg_price) / self.avg_price


# ─────────────────────────────────────────────────────────────────────────────
# 주문 결과 데이터 클래스
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class OrderResult:
    success:      bool
    action:       str        # "BUY" | "SELL" | "SKIP" | "ERROR"
    ticker:       str
    ticker_name:  str
    quantity:     int   = 0
    price:        float = 0.0
    amount:       float = 0.0   # 주문 금액
    reason:       str   = ""
    timestamp:    str   = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Trader 메인 클래스
# ─────────────────────────────────────────────────────────────────────────────
class Trader:
    """
    신호 수신 → 주문 실행 → 포지션 관리 통합 클래스.

    싱글톤 패턴 사용. Flask 앱에서 단일 인스턴스 공유.
    """

    _instance = None
    _lock      = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.config     = RiskConfig()
        self._positions: dict[str, Position] = {}   # {ticker: Position}
        self._order_lock = threading.Lock()          # 동시 주문 방지
        self._order_log: list[dict] = []             # 주문 이력 (메모리)

        logger.info("[Trader] 초기화 완료")
        logger.info(f"[Trader] 손절: {self.config.STOP_LOSS_PCT*100:.1f}% | "
                    f"익절: {self.config.TAKE_PROFIT_PCT*100:.1f}% | "
                    f"최대포지션: {self.config.MAX_POSITIONS}개")

    # ──────────────────────────────────────────────────────────────
    # 키움 헬퍼
    # ──────────────────────────────────────────────────────────────

    def _get_kiwoom(self):
        """kiwoom_worker 싱글톤 반환. 로그인 미완료 시 None."""
        try:
            from kiwoom_client import kiwoom
            if kiwoom.get_login_state() != 1:
                logger.warning("[Trader] 키움 로그인 필요")
                return None
            return kiwoom
        except Exception as e:
            logger.error(f"[Trader] kiwoom_worker import 실패: {e}")
            return None

    def _get_balance(self) -> float:
        """
        계좌 예수금(주문 가능 금액) 조회.
        키움 opw00001 TR — kiwoom_worker 에 get_balance() 구현 필요.
        미구현 시 0 반환 (주문 차단됨).
        """
        kiwoom = self._get_kiwoom()
        if kiwoom is None:
            return 0.0
        try:
            if hasattr(kiwoom, 'get_balance'):
                return float(kiwoom.get_balance() or 0)
            # get_balance 미구현 시 경고 후 0 반환
            logger.warning(
                "[Trader] kiwoom.get_balance() 미구현 → 주문 차단\n"
                "  kiwoom_worker.py 에 opw00001 TR 추가 필요"
            )
            return 0.0
        except Exception as e:
            logger.error(f"[Trader] 잔고 조회 실패: {e}")
            return 0.0

    def _get_current_price(self, ticker: str) -> float:
        """현재가 조회 (opt10001)."""
        kiwoom = self._get_kiwoom()
        if kiwoom is None:
            return 0.0
        try:
            data = kiwoom.get_best_price(ticker)
            return float(data.get("price", 0)) if data else 0.0
        except Exception as e:
            logger.error(f"[Trader] 현재가 조회 실패 ({ticker}): {e}")
            return 0.0

    def _send_order(self, ticker: str, order_type: str,
                    quantity: int, price: int = 0) -> bool:
        """
        ⛔ 실주문 송신 — 영구 차단됨.

        모든 실매수/실매도는 이 단일 지점을 통과한다. 주문 대행(투자일임)을
        막기 위해, 여기서 무조건 거부하고 외부 증권사 API(키움 SendOrder, KIS
        주문 등)를 절대 호출하지 않는다. LIVE_ORDER_EXECUTION_DISABLED 상수로
        하드코딩되어 있어 환경변수로 우회할 수 없다.
        """
        logger.error(
            "[Trader] ⛔ 실주문 차단: %s %s %s주 @%s — 이 서비스는 정보 제공만 하며 "
            "주문 대행(투자일임)은 영구 비활성화되어 있습니다.",
            order_type, ticker, quantity, "시장가" if price == 0 else price,
        )
        return False

    # ──────────────────────────────────────────────────────────────
    # 사전 검증
    # ──────────────────────────────────────────────────────────────

    def _is_market_open(self) -> bool:
        """
        현재 KRX 정규 거래시간 여부 확인.
        장 마감 NO_BUY_BEFORE_CLOSE_MIN 분 전부터 신규 매수 차단.
        """
        from kiwoom_client import fetch_market_session
        session = fetch_market_session()
        if not session.get("krx", False):
            return False

        # 장 마감 n분 전 신규 매수 차단
        try:
            import pytz
            from datetime import time as dtime
            KST    = pytz.timezone('Asia/Seoul')
            now    = datetime.now(KST).time()
            cutoff_min = 15 * 60 + 30 - self.config.NO_BUY_BEFORE_CLOSE_MIN
            cutoff = dtime(cutoff_min // 60, cutoff_min % 60)
            if now >= cutoff:
                logger.info(f"[Trader] 장 마감 {self.config.NO_BUY_BEFORE_CLOSE_MIN}분 전 → 신규 매수 차단")
                return False
        except Exception:
            pass

        return True

    def _check_volume(self, ticker: str) -> bool:
        """최소 거래량 필터."""
        kiwoom = self._get_kiwoom()
        if kiwoom is None:
            return False
        try:
            data = kiwoom.get_best_price(ticker)
            vol  = int(data.get("volume", 0)) if data else 0
            if vol < self.config.MIN_VOLUME:
                logger.info(f"[Trader] 거래량 부족 ({ticker}): {vol:,} < {self.config.MIN_VOLUME:,}")
                return False
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────
    # 포지션 사이징
    # ──────────────────────────────────────────────────────────────

    def _calc_quantity(self, current_price: float) -> int:
        """
        매수 수량 계산.
        계좌 잔고 × MAX_POSITION_RATIO ÷ 현재가 (1주 단위 절삭).
        """
        if current_price <= 0:
            return 0
        balance      = self._get_balance()
        invest_amount = balance * self.config.MAX_POSITION_RATIO
        quantity     = int(invest_amount // current_price)
        logger.info(
            f"[Trader] 포지션 사이징: 잔고={balance:,.0f}원 | "
            f"투자금={invest_amount:,.0f}원 | "
            f"수량={quantity}주 @ {current_price:,.0f}원"
        )
        return quantity

    # ──────────────────────────────────────────────────────────────
    # 손절 / 익절 체크
    # ──────────────────────────────────────────────────────────────

    def _check_exit_conditions(self) -> list[OrderResult]:
        """
        보유 포지션 전체를 순회하여 손절/익절 조건을 확인합니다.
        조건 충족 시 자동 매도 주문을 실행합니다.

        스케줄러(APScheduler 등)에서 주기적으로 호출하세요:
          from apscheduler.schedulers.background import BackgroundScheduler
          scheduler = BackgroundScheduler()
          scheduler.add_job(trader.check_exits, 'interval', minutes=1)
          scheduler.start()
        """
        results = []
        for ticker, pos in list(self._positions.items()):
            current_price = self._get_current_price(ticker)
            if current_price <= 0:
                continue

            pnl_pct = (current_price - pos.avg_price) / pos.avg_price
            reason  = None

            if current_price <= pos.stop_price:
                reason = f"손절 ({pnl_pct*100:.2f}% ≤ {self.config.STOP_LOSS_PCT*100:.1f}%)"
            elif current_price >= pos.target_price:
                reason = f"익절 ({pnl_pct*100:.2f}% ≥ {self.config.TAKE_PROFIT_PCT*100:.1f}%)"

            if reason:
                result = self._execute_sell(ticker, pos, current_price, reason)
                results.append(result)

        return results

    # ──────────────────────────────────────────────────────────────
    # 매수 실행
    # ──────────────────────────────────────────────────────────────

    def _execute_buy(self, ticker: str, ticker_name: str,
                     current_price: float, prob_buy: float) -> OrderResult:
        """
        매수 주문 실행 및 포지션 등록.

        Args:
            ticker       : 종목코드
            ticker_name  : 종목명
            current_price: 현재가
            prob_buy     : 매수 확률 (signal.py 출력)
        """
        # ── ⛔ 실매매(주문 대행) 영구 차단 ──────────────────────────────
        if LIVE_ORDER_EXECUTION_DISABLED:
            return OrderResult(
                success=False, action="BLOCKED",
                ticker=ticker, ticker_name=ticker_name,
                price=current_price,
                reason="실매매 비활성화 — 주문 대행(투자일임) 금지. 정보 제공만 제공합니다.",
            )

        # ── 중복 보유 차단 ──────────────────────────────────────────────
        if ticker in self._positions:
            return OrderResult(
                success=False, action="SKIP",
                ticker=ticker, ticker_name=ticker_name,
                price=current_price,
                reason="이미 보유 중 → 중복 매수 차단",
            )

        # ── 최대 포지션 수 초과 ─────────────────────────────────────────
        if len(self._positions) >= self.config.MAX_POSITIONS:
            return OrderResult(
                success=False, action="SKIP",
                ticker=ticker, ticker_name=ticker_name,
                price=current_price,
                reason=f"최대 포지션 {self.config.MAX_POSITIONS}개 초과",
            )

        # ── 수량 계산 ───────────────────────────────────────────────────
        quantity = self._calc_quantity(current_price)
        if quantity <= 0:
            return OrderResult(
                success=False, action="SKIP",
                ticker=ticker, ticker_name=ticker_name,
                price=current_price,
                reason="주문 가능 수량 0 (잔고 부족 또는 잔고 조회 실패)",
            )

        # ── 주문가 결정 (시장가 / 지정가) ──────────────────────────────
        if self.config.ORDER_TYPE == "시장가":
            order_price = 0
        else:
            order_price = int(current_price * (1 + self.config.SLIPPAGE_PCT))

        # ── 주문 실행 ───────────────────────────────────────────────────
        ok = self._send_order(ticker, "매수", quantity, order_price)
        if not ok:
            return OrderResult(
                success=False, action="ERROR",
                ticker=ticker, ticker_name=ticker_name,
                quantity=quantity, price=current_price,
                reason="주문 API 실패",
            )

        # ── 포지션 등록 ─────────────────────────────────────────────────
        stop_price   = round(current_price * (1 + self.config.STOP_LOSS_PCT),  -1)
        target_price = round(current_price * (1 + self.config.TAKE_PROFIT_PCT), -1)
        self._positions[ticker] = Position(
            ticker=ticker,
            ticker_name=ticker_name,
            quantity=quantity,
            avg_price=current_price,
            entry_time=datetime.now().isoformat(),
            stop_price=stop_price,
            target_price=target_price,
            last_signal="BUY",
        )

        amount = quantity * current_price
        result = OrderResult(
            success=True, action="BUY",
            ticker=ticker, ticker_name=ticker_name,
            quantity=quantity, price=current_price, amount=amount,
            reason=(
                f"매수 확률 {prob_buy*100:.1f}% | "
                f"손절가={stop_price:,.0f} | 익절가={target_price:,.0f}"
            ),
        )

        logger.info(
            f"[Trader] ✅ 매수 체결: {ticker_name}({ticker}) "
            f"{quantity}주 @ {current_price:,.0f}원 = {amount:,.0f}원 | "
            f"손절={stop_price:,.0f} 익절={target_price:,.0f}"
        )
        return result

    # ──────────────────────────────────────────────────────────────
    # 매도 실행
    # ──────────────────────────────────────────────────────────────

    def _execute_sell(self, ticker: str, pos: Position,
                      current_price: float, reason: str) -> OrderResult:
        """
        매도 주문 실행 및 포지션 해제.

        Args:
            ticker       : 종목코드
            pos          : 현재 포지션 정보
            current_price: 현재가
            reason       : 매도 사유 (손절/익절/신호)
        """
        # ── ⛔ 실매매(주문 대행) 영구 차단 ──────────────────────────────
        if LIVE_ORDER_EXECUTION_DISABLED:
            return OrderResult(
                success=False, action="BLOCKED",
                ticker=ticker, ticker_name=pos.ticker_name,
                quantity=pos.quantity, price=current_price,
                reason="실매매 비활성화 — 주문 대행(투자일임) 금지. 정보 제공만 제공합니다.",
            )

        if self.config.ORDER_TYPE == "시장가":
            order_price = 0
        else:
            order_price = int(current_price * (1 - self.config.SLIPPAGE_PCT))

        ok = self._send_order(ticker, "매도", pos.quantity, order_price)
        if not ok:
            return OrderResult(
                success=False, action="ERROR",
                ticker=ticker, ticker_name=pos.ticker_name,
                quantity=pos.quantity, price=current_price,
                reason=f"매도 주문 API 실패 ({reason})",
            )

        # 포지션 제거
        pnl_pct = (current_price - pos.avg_price) / pos.avg_price
        amount  = pos.quantity * current_price
        del self._positions[ticker]

        result = OrderResult(
            success=True, action="SELL",
            ticker=ticker, ticker_name=pos.ticker_name,
            quantity=pos.quantity, price=current_price, amount=amount,
            reason=f"{reason} | PnL={pnl_pct*100:+.2f}%",
        )

        logger.info(
            f"[Trader] ✅ 매도 체결: {pos.ticker_name}({ticker}) "
            f"{pos.quantity}주 @ {current_price:,.0f}원 | "
            f"PnL={pnl_pct*100:+.2f}% | 사유={reason}"
        )
        return result

    # ──────────────────────────────────────────────────────────────
    # 공개 메서드
    # ──────────────────────────────────────────────────────────────

    def run_signal(self, ticker: str, ticker_name: str = "",
                   ohlcv_df=None) -> OrderResult:
        """
        단일 종목 신호 조회 → 매매 실행 통합 진입점.

        signal.py.predict() 를 호출해 BUY/SELL/HOLD 신호를 받고
        리스크 조건을 통과한 경우에만 주문을 실행합니다.

        Args:
            ticker      : 종목코드 (예: "005930")
            ticker_name : 종목명   (예: "삼성전자")
            ohlcv_df    : OHLCV DataFrame (None 이면 내부에서 자동 조회)

        Returns:
            OrderResult — action: "BUY"|"SELL"|"HOLD"|"SKIP"|"ERROR"
        """
        name = ticker_name or ticker

        with self._order_lock:   # 동시 주문 방지
            try:
                # ── 1. 신호 생성 ─────────────────────────────────────────
                from trading.signal import predict
                sig = predict(ticker, name, ohlcv_df)

                if sig["signal"] == "ERROR":
                    return OrderResult(
                        success=False, action="ERROR",
                        ticker=ticker, ticker_name=name,
                        reason=sig.get("reason", "signal.py 오류"),
                    )

                current_price = sig.get("price", 0.0)
                signal        = sig["signal"]
                prob_buy      = sig.get("prob_buy",  0.0)
                prob_sell     = sig.get("prob_sell", 0.0)

                logger.info(
                    f"[Trader] 신호: {name}({ticker}) → {signal} | "
                    f"buy={prob_buy:.1%} sell={prob_sell:.1%} | "
                    f"현재가={current_price:,.0f}원"
                )

                # ── 2. HOLD → 손절/익절만 체크 ───────────────────────────
                if signal == "HOLD":
                    exits = self._check_exit_conditions()
                    if exits:
                        return exits[0]
                    return OrderResult(
                        success=True, action="HOLD",
                        ticker=ticker, ticker_name=name,
                        price=current_price,
                        reason=sig.get("reason", "관망"),
                    )

                # ── 3. BUY 처리 ──────────────────────────────────────────
                if signal == "BUY":
                    # 확률 임계값 재검증
                    if prob_buy < self.config.MIN_BUY_PROB:
                        return OrderResult(
                            success=False, action="SKIP",
                            ticker=ticker, ticker_name=name,
                            price=current_price,
                            reason=f"매수 확률 {prob_buy:.1%} < 임계값 {self.config.MIN_BUY_PROB:.1%}",
                        )
                    # 장 시간 확인
                    if not self._is_market_open():
                        return OrderResult(
                            success=False, action="SKIP",
                            ticker=ticker, ticker_name=name,
                            price=current_price,
                            reason="장 외 시간 또는 마감 임박",
                        )
                    # 거래량 필터
                    if not self._check_volume(ticker):
                        return OrderResult(
                            success=False, action="SKIP",
                            ticker=ticker, ticker_name=name,
                            price=current_price,
                            reason="거래량 부족",
                        )
                    result = self._execute_buy(ticker, name, current_price, prob_buy)

                # ── 4. SELL 처리 ─────────────────────────────────────────
                elif signal == "SELL":
                    if ticker not in self._positions:
                        return OrderResult(
                            success=False, action="SKIP",
                            ticker=ticker, ticker_name=name,
                            price=current_price,
                            reason="보유 포지션 없음 → 매도 스킵",
                        )
                    if prob_sell < self.config.MIN_SELL_PROB:
                        return OrderResult(
                            success=False, action="SKIP",
                            ticker=ticker, ticker_name=name,
                            price=current_price,
                            reason=f"매도 확률 {prob_sell:.1%} < 임계값 {self.config.MIN_SELL_PROB:.1%}",
                        )
                    pos    = self._positions[ticker]
                    reason = f"SELL 신호 (확률={prob_sell:.1%})"
                    result = self._execute_sell(ticker, pos, current_price, reason)

                else:
                    result = OrderResult(
                        success=False, action="SKIP",
                        ticker=ticker, ticker_name=name,
                        price=current_price,
                        reason=f"알 수 없는 신호: {signal}",
                    )

                # ── 5. 주문 이력 저장 ────────────────────────────────────
                self._order_log.append(result.to_dict())
                if len(self._order_log) > 1000:
                    self._order_log = self._order_log[-500:]

                return result

            except Exception as e:
                logger.error(f"[Trader] run_signal 오류 ({ticker}): {e}", exc_info=True)
                return OrderResult(
                    success=False, action="ERROR",
                    ticker=ticker, ticker_name=name,
                    reason=str(e),
                )

    def check_exits(self) -> list[OrderResult]:
        """
        보유 포지션 손절/익절 일괄 체크.
        APScheduler 또는 별도 스레드에서 주기적으로 호출하세요.
        """
        with self._order_lock:
            results = self._check_exit_conditions()
            for r in results:
                self._order_log.append(r.to_dict())
            return results

    def get_positions(self) -> list[dict]:
        """현재 보유 포지션 목록 (routes 에서 JSON 반환용)."""
        result = []
        for ticker, pos in self._positions.items():
            current_price = self._get_current_price(ticker)
            pnl_pct = (
                (current_price - pos.avg_price) / pos.avg_price
                if pos.avg_price > 0 else 0.0
            )
            d = asdict(pos)
            d.update({
                "current_price": current_price,
                "pnl_pct":       round(pnl_pct, 4),
                "pnl_amount":    round((current_price - pos.avg_price) * pos.quantity, 0),
            })
            result.append(d)
        return result

    def get_order_log(self, limit: int = 50) -> list[dict]:
        """최근 주문 이력 반환."""
        return list(reversed(self._order_log[-limit:]))

    def get_summary(self) -> dict:
        """트레이더 상태 요약."""
        return {
            "position_count":   len(self._positions),
            "max_positions":    self.config.MAX_POSITIONS,
            "stop_loss_pct":    self.config.STOP_LOSS_PCT,
            "take_profit_pct":  self.config.TAKE_PROFIT_PCT,
            "min_buy_prob":     self.config.MIN_BUY_PROB,
            "order_type":       self.config.ORDER_TYPE,
            "order_log_count":  len(self._order_log),
        }


# ── 싱글톤 인스턴스 ──
trader = Trader()