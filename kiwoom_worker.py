import sys
import threading
import time
import os
import pandas as pd
from datetime import datetime, time as dtime
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QObject, QTimer

load_dotenv()


# ══════════════════════════════════════════════════════
# ── 안전한 파싱 헬퍼 ──
# ══════════════════════════════════════════════════════

def safe_int(val, default=0):
    """문자열 → 절댓값 정수 (빈 값/오류 시 default)"""
    try:
        return abs(int(str(val).replace(',', '').strip()))
    except Exception:
        return default

def safe_signed_int(val, default=0):
    """문자열 → 부호 있는 정수"""
    try:
        return int(str(val).replace(',', '').strip())
    except Exception:
        return default

def safe_float(val, default=0.0):
    """문자열 → 실수"""
    try:
        return float(str(val).replace(',', '').strip())
    except Exception:
        return default

def decode_kiwoom(s: str) -> str:
    """키움 COM 반환 문자열의 CP949→latin-1 오디코딩 복원"""
    try:
        return s.encode('latin-1').decode('cp949')
    except Exception:
        return s


# ══════════════════════════════════════════════════════
# ── 시장 세션 판별 ──
# ══════════════════════════════════════════════════════

def get_market_session() -> dict:
    """
    현재 한국 시각 기준 거래 세션을 반환합니다.

    거래소별 시간:
    ┌─────────────────────────────┐
    │ NXT 프리마켓  : 08:00~09:00 │
    │ KRX + NXT 동시: 09:00~15:30 │
    │ NXT 시간외    : 15:30~20:00 │
    │ 장 마감       : 20:00~08:00 │
    └─────────────────────────────┘

    주말(토/일) 및 공휴일은 CLOSED로 반환됩니다.
    (공휴일 자동 감지는 미지원 — KRX API 별도 확인 필요)
    """
    try:
        import pytz
        KST = pytz.timezone('Asia/Seoul')
        now_kst = datetime.now(KST)
    except ImportError:
        from datetime import timezone, timedelta
        KST = timezone(timedelta(hours=9))
        now_kst = datetime.now(KST)

    weekday = now_kst.weekday()   # 0=월 ~ 6=일
    now_t   = now_kst.time()

    if weekday >= 5:
        return {
            "session":       "CLOSED",
            "label":         "주말 (장 마감)",
            "krx":           False,
            "nxt":           False,
            "price_source":  "NONE",
            "note":          "토요일/일요일은 모든 거래소 마감",
        }

    NXT_PRE_OPEN = dtime(8,  0)
    KRX_OPEN     = dtime(9,  0)
    KRX_CLOSE    = dtime(15, 30)
    NXT_CLOSE    = dtime(20, 0)

    if now_t < NXT_PRE_OPEN or now_t >= NXT_CLOSE:
        return {
            "session":      "CLOSED",
            "label":        "장 마감",
            "krx":          False,
            "nxt":          False,
            "price_source": "NONE",
            "note":         "NXT 운영 시간: 08:00 ~ 20:00",
        }
    elif now_t < KRX_OPEN:
        return {
            "session":      "NXT_PRE",
            "label":        "NXT 프리마켓",
            "krx":          False,
            "nxt":          True,
            "price_source": "NXT",
            "note":         "KRX 개장 전 NXT 단독 운영 (08:00~09:00)",
        }
    elif now_t < KRX_CLOSE:
        return {
            "session":      "BOTH",
            "label":        "KRX + NXT 동시",
            "krx":          True,
            "nxt":          True,
            "price_source": "KRX",
            "note":         "KRX 우선, NXT 병행 (09:00~15:30)",
        }
    else:
        return {
            "session":      "NXT_AFTER",
            "label":        "NXT 시간외",
            "krx":          False,
            "nxt":          True,
            "price_source": "NXT",
            "note":         "KRX 폐장 후 NXT 단독 운영 (15:30~20:00)",
        }


# ══════════════════════════════════════════════════════
# ── 키움 API Qt 클래스 ──
# ══════════════════════════════════════════════════════

class KiwoomAPI(QObject):
    """
    키움 OpenAPI COM 객체를 감싸는 Qt 기반 클래스.
    Qt 이벤트 루프가 실행 중인 스레드에서만 동작해야 함.
    """

    def __init__(self):
        super().__init__()

        self.api = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.api.OnEventConnect.connect(self._on_login)
        self.api.OnReceiveTrData.connect(self._on_tr_data)

        self._login_event  = threading.Event()
        self._login_result = None
        self._tr_event     = threading.Event()
        self._tr_data      = {}
        self._account_no   = None
        self._deposit      = None   # opw00018 싱글 데이터에서 추출한 예수금

        # ── 조건검색 이벤트 연결 ──
        self.api.OnReceiveConditionVer.connect(self._on_condition_ver)
        self.api.OnReceiveTrCondition.connect(self._on_tr_condition)
        self.api.OnReceiveRealCondition.connect(self._on_real_condition)

        # 조건검색 동기화용
        self._condition_event   = threading.Event()
        self._condition_list    = {}    # {조건명: 인덱스}
        self._condition_result  = []    # 검색 결과 종목코드 리스트
        self._real_condition_cb = None  # 실시간 편입/이탈 콜백 (선택)

    def _on_login(self, err_code):
        """로그인 결과 콜백 (0: 성공, 음수: 실패)"""
        _ERR = {
            0:    "로그인 성공",
            -100: "사용자 정보교환 실패 (네트워크 확인)",
            -101: "서버 접속 실패 (방화벽/네트워크 확인)",
            -102: "버전처리 실패 → 키움 OpenAPI+ 업데이트 필요",
            -103: "개인방화벽 실패",
        }
        msg = _ERR.get(err_code, f"알 수 없는 오류 ({err_code})")
        print(f"[Kiwoom] 로그인 콜백: {err_code} — {msg}")
        self._login_result = err_code
        self._login_msg    = msg
        if err_code == 0:
            raw = self.api.dynamicCall("GetLoginInfo(QString)", ["ACCNO"])
            accounts = [a for a in raw.split(';') if a.strip()]
            self._account_no = accounts[0] if accounts else None
            print(f"[Kiwoom] 계좌번호 저장 완료: {self._account_no}")
        self._login_event.set()

    def _on_tr_data(self, screen_no, rq_name, tr_code, record_name, prev_next, *args):
        """
        TR 데이터 수신 콜백.
        rq_name 별로 분기하여 self._tr_data 에 저장하고 _tr_event 를 set.
        """
        result = {}

        # ── 주식 기본정보 / 현재가 (opt10001) — KRX 및 NXT 공통 ──
        if rq_name in ("opt10001_req", "opt10001_nxt_req"):
            price_fields = [
                "종목명", "현재가", "기준가", "전일대비", "등락율",
                "거래량", "거래대금", "시가", "고가", "저가",
            ]
            finance_fields = [
                "시가총액", "PER", "PBR", "EPS", "BPS",
                "배당수익률", "연중최고", "연중최저",
                "외국인소진율", "상장주식수", "ROE",
            ]
            for key in price_fields + finance_fields:
                val = self.api.dynamicCall(
                    "GetCommData(QString, QString, int, QString)",
                    [tr_code, rq_name, 0, key]
                ).strip()
                if key == "종목명":
                    val = decode_kiwoom(val)
                result[key] = val
            result["_rq"] = rq_name

        # ── 계좌 보유종목 (opw00018 / OPW00004 공통) ──
        elif rq_name in ("opw00018_req", "opw00004_req"):
            count = int(self.api.dynamicCall(
                "GetRepeatCnt(QString, QString)", [tr_code, rq_name]
            ) or 0)
            if count == 0 and record_name:
                count = int(self.api.dynamicCall(
                    "GetRepeatCnt(QString, QString)", [tr_code, record_name]
                ) or 0)
            print(f"[Kiwoom] {tr_code} GetRepeatCnt → {count}개 "
                  f"(rq='{rq_name}', record='{record_name}')")

            # 싱글 데이터: 예수금 추출
            # 실제 현금 필드 우선, 없으면 총평가금액(주식 시가합계)으로 대체
            _cash_fields = [
                "예수금", "출금가능금액", "D+2출금가능금액",
                "주문가능현금", "총예탁자산", "D+1출금가능금액",
                "예수금총액", "주문가능금액", "가용예수금",
                "인출가능금액", "현금주문가능금액",
            ]
            _fallback_fields = ["총평가금액"]  # 현금 필드 모두 실패 시 주식 시가합계
            deposit = 0
            deposit_field = ""
            for _record in [rq_name, tr_code, ""]:
                for _f in _cash_fields + _fallback_fields:
                    _raw = self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [tr_code, _record, 0, _f]
                    ).strip()
                    _v = safe_int(_raw)
                    if _v > 0 and deposit == 0:
                        deposit = _v
                        deposit_field = _f
                        print(f"[Kiwoom] 예수금 채택: field={_f!r} → {_v:,}원")
                if deposit > 0:
                    break
            if deposit == 0:
                print(f"[Kiwoom] 예수금 추출 실패 — 0원 처리")
            self._deposit = deposit

            code_field = "종목번호" if rq_name == "opw00018_req" else "종목코드"
            avg_field  = "매입단가"

            holdings = []
            for i in range(count):
                def get_field(field, idx=i, _rq=rq_name, _tr=tr_code):
                    return self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [_tr, _rq, idx, field]
                    ).strip()
                code      = get_field(code_field).strip().lstrip('A')
                name      = decode_kiwoom(get_field("종목명").strip())
                quantity  = safe_int(get_field("보유수량"))
                avg_price = 0
                for _af in ["매입단가", "매입평균가", "평균단가", "기준가"]:
                    avg_price = safe_int(get_field(_af))
                    if avg_price > 0:
                        break
                # 매입금액/수량으로 역산 (모의투자 등 단가 필드가 없는 경우)
                if avg_price == 0 and quantity > 0:
                    buy_amount = safe_int(get_field("매입금액"))
                    if buy_amount > 0:
                        avg_price = buy_amount // quantity
                print(f"[Kiwoom] 종목 {i}: code={repr(code)}, name={repr(name)}, "
                      f"qty={quantity}, avg={avg_price}")
                if code and quantity > 0:
                    holdings.append({
                        "code":      code,
                        "name":      name,
                        "quantity":  quantity,
                        "avg_price": avg_price,
                    })
            result = {"type": "holdings", "holdings": holdings, "deposit": deposit}

        # ── 계좌 기간별 주문체결 내역 (opw00015) ──
        elif rq_name == "opw00015_req":
            # record_name fallback: opw00018과 동일하게 여러 식별자 시도
            count = int(self.api.dynamicCall(
                "GetRepeatCnt(QString, QString)", [tr_code, rq_name]
            ) or 0)
            if count == 0 and record_name:
                count = int(self.api.dynamicCall(
                    "GetRepeatCnt(QString, QString)", [tr_code, record_name]
                ) or 0)
            if count == 0:
                count = int(self.api.dynamicCall(
                    "GetRepeatCnt(QString, QString)", [tr_code, tr_code]
                ) or 0)
            print(f"[Kiwoom] opw00015 GetRepeatCnt → {count}행 "
                  f"(rq={rq_name!r}, record={record_name!r}, tr={tr_code!r})")

            # GetCommData record name도 동일하게 동작하는 식별자 선택
            _rec = rq_name  # 기본값; 필요시 tr_code 또는 record_name으로 교체
            trades = []
            for i in range(count):
                def get_field(field, idx=i, _r=_rec, _tr=tr_code):
                    return self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [_tr, _r, idx, field]
                    ).strip()
                code       = get_field("종목코드").lstrip('A')
                name       = decode_kiwoom(get_field("종목명"))
                order_type = get_field("매매구분")
                qty        = safe_int(get_field("체결수량"))
                price      = safe_int(get_field("체결단가"))
                trade_date = get_field("체결일자")
                trade_time = get_field("체결시간")
                if i == 0:
                    print(f"[Kiwoom] opw00015 1행 샘플: code={code!r} name={name!r} "
                          f"type={order_type!r} qty={qty} price={price} "
                          f"date={trade_date!r} time={trade_time!r}")
                if code and qty > 0 and price > 0:
                    is_buy = "매수" in order_type
                    trades.append({
                        "code":     code,
                        "name":     name,
                        "type":     "buy" if is_buy else "sell",
                        "quantity": qty,
                        "price":    price,
                        "total":    price * qty,
                        "date":     trade_date,
                        "time":     trade_time,
                    })
            result = {"type": "period_trades", "trades": trades}
            print(f"[Kiwoom] opw00015 수신: {count}행, {len(trades)}건")

        # ── 계좌별 당일 체결현황 (opw00007) ──
        elif rq_name == "opw00007_req":
            count = int(self.api.dynamicCall(
                "GetRepeatCnt(QString, QString)", [tr_code, rq_name]
            ) or 0)
            trades = []
            for i in range(count):
                def get_field(field, idx=i, _rq=rq_name, _tr=tr_code):
                    return self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [_tr, _rq, idx, field]
                    ).strip()
                code       = get_field("종목번호").lstrip('A')
                name       = decode_kiwoom(get_field("종목명"))
                order_type = get_field("주문구분")   # "매수"/"매도" or "+매수"/"-매도"
                qty        = safe_int(get_field("체결량"))
                price      = safe_int(get_field("체결가"))
                time_str   = get_field("주문시간")   # HHMMSS
                if code and qty > 0 and price > 0:
                    is_buy = "매수" in order_type
                    trades.append({
                        "code":     code,
                        "name":     name,
                        "type":     "buy" if is_buy else "sell",
                        "quantity": qty,
                        "price":    price,
                        "total":    price * qty,
                        "time":     time_str,
                    })
            result = {"type": "daily_trades", "trades": trades}
            print(f"[Kiwoom] opw00007 수신: {count}행, 체결 {len(trades)}건")

        # ── 계좌별 실현손익 (opt10073) ──
        elif rq_name == "opt10073_req":
            count = int(self.api.dynamicCall(
                "GetRepeatCnt(QString, QString)", [tr_code, rq_name]
            ) or 0)
            stocks = []
            pnl_sum = 0
            for i in range(count):
                def gf(field, idx=i, _rq=rq_name, _tr=tr_code):
                    return self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [_tr, _rq, idx, field]
                    ).strip()
                code = gf("종목코드").lstrip('A')
                name = decode_kiwoom(gf("종목명"))
                date = gf("일자") or gf("체결일자") or gf("거래일자")
                qty        = safe_int(gf("체결량") or gf("수량"))
                buy_price  = safe_int(gf("매입단가") or gf("매입가") or gf("평균단가"))
                sell_price = safe_int(gf("체결가")  or gf("체결단가") or gf("매도단가"))

                # opt10073의 정식 실현손익 필드는 '당일매도손익'. (기존 코드가 잘못된
                # 필드명을 읽어 항상 0이 나오던 버그) 변형 필드명도 폴백으로 시도.
                pnl = 0
                for _f in ["당일매도손익", "실현손익", "손익금액", "순손익금액", "실현손익합계"]:
                    pnl = safe_signed_int(gf(_f))
                    if pnl != 0:
                        break
                if pnl == 0 and sell_price > 0 and buy_price > 0 and qty > 0:
                    pnl = (sell_price - buy_price) * qty

                if i == 0:
                    print(f"[Kiwoom] opt10073 1행 샘플: code={code!r} date={date!r} "
                          f"qty={qty} buy={buy_price} sell={sell_price} pnl={pnl}")
                pnl_sum += pnl
                if code:
                    stocks.append({"code": code, "name": name, "pnl": pnl,
                                   "date": date, "quantity": qty,
                                   "buy_price": buy_price, "sell_price": sell_price})

            total_pnl = pnl_sum
            result = {"type": "realized_pnl", "total_pnl": total_pnl, "stocks": stocks}
            print(f"[Kiwoom] opt10073 수신: 실현손익합계={total_pnl:,}원, {count}종목")

        # ── 주식투자자별매매동향 (opt10059) ──
        # 기관/외국인/개인 순매수 금액(천원) 일별 데이터
        # feature.py 의 calc_supply_features() 에서 소비
        elif rq_name == "opt10059_req":
            count = int(self.api.dynamicCall(
                "GetRepeatCnt(QString, QString)", [tr_code, rq_name]
            ) or 0)
            rows = []
            for i in range(count):
                def get_field(field, idx=i, _rq=rq_name, _tr=tr_code):
                    return self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [_tr, _rq, idx, field]
                    ).strip()
                rows.append({
                    "date":        get_field("일자"),
                    "individual":  safe_signed_int(get_field("개인투자자")),
                    "foreign":     safe_signed_int(get_field("외국인투자자")),
                    "institution": safe_signed_int(get_field("기관계")),
                })
            result = {"type": "investor_trend", "rows": rows}
            print(f"[Kiwoom] opt10059 수신: {count}행")

        # ── 주식일봉차트조회 (opt10081) ──
        # OHLCV 일봉 데이터 — feature.py 의 calc_technical_features() 에서 소비
        elif rq_name == "opt10081_req":
            count = int(self.api.dynamicCall(
                "GetRepeatCnt(QString, QString)", [tr_code, rq_name]
            ) or 0)
            rows = []
            for i in range(count):
                def get_field(field, idx=i, _rq=rq_name, _tr=tr_code):
                    return self.api.dynamicCall(
                        "GetCommData(QString, QString, int, QString)",
                        [_tr, _rq, idx, field]
                    ).strip()
                rows.append({
                    "date":   get_field("일자"),
                    "open":   safe_int(get_field("시가")),
                    "high":   safe_int(get_field("고가")),
                    "low":    safe_int(get_field("저가")),
                    "close":  safe_int(get_field("현재가")),  # 일봉에서 현재가 = 종가
                    "volume": safe_int(get_field("거래량")),
                })
            result = {"type": "ohlcv", "rows": rows}
            print(f"[Kiwoom] opt10081 수신: {count}행")

        # ── 선물시세조회 (opt50001) ──
        # KOSPI200 선물 현재가·등락율. sidecar_monitor 의 선물 선행신호로 사용.
        elif rq_name == "opt50001_req":
            def get_field(field, _rq=rq_name, _tr=tr_code):
                return self.api.dynamicCall(
                    "GetCommData(QString, QString, int, QString)",
                    [_tr, _rq, 0, field]
                ).strip()
            price = abs(safe_int(get_field("현재가")))
            try:
                rate = abs(float((get_field("등락율") or "0").replace("+", "").replace("%", "")))
            except Exception:
                rate = 0.0
            sign = get_field("대비기호")          # 1상한 2상승 3보합 4하한 5하락
            if sign in ("4", "5"):
                rate = -rate
            result = {"type": "futures", "price": float(price), "change": rate}
            print(f"[Kiwoom] opt50001 수신: 현재가={price} 등락율={rate}")

        self._tr_data = result
        self._tr_event.set()

    # ── 조건검색 목록 수신 콜백 ──
    def _on_condition_ver(self, ret, msg):
        """GetConditionNameList 요청 후 조건식 목록이 준비되면 호출됨"""
        if ret == 1:
            raw = self.api.dynamicCall("GetConditionNameList()")
            # COM 반환값이 CP949 바이트를 latin-1로 잘못 디코딩한 경우 복원
            try:
                raw = raw.encode('latin-1').decode('cp949')
            except Exception:
                pass
            # 형식: "0^조건명A;1^조건명B;"
            self._condition_list = {}
            for item in raw.split(';'):
                item = item.strip()
                if '^' not in item:
                    continue
                idx, name = item.split('^', 1)
                self._condition_list[name.strip()] = int(idx.strip())
            print(f"[Kiwoom] 조건식 목록 수신 완료: {list(self._condition_list.keys())}")
        else:
            print(f"[Kiwoom] 조건식 목록 수신 실패: {msg}")
        self._condition_event.set()

    # ── 조건검색 결과 수신 콜백 ──
    def _on_tr_condition(self, screen_no, code_list, condition_name, index, next_flag):
        """SendCondition(조회구분=0) 호출 후 결과 종목 리스트 수신"""
        try:
            condition_name = condition_name.encode('latin-1').decode('cp949')
        except Exception:
            pass
        codes = [c.strip() for c in code_list.split(';') if c.strip()]
        self._condition_result = codes
        print(f"[Kiwoom] 조건검색 결과: '{condition_name}' → {len(codes)}개 종목")
        self._condition_event.set()

    # ── 실시간 조건검색 편입/이탈 콜백 ──
    def _on_real_condition(self, code, event_type, condition_name, condition_index):
        """
        SendCondition(조회구분=1) 등록 후 종목 편입/이탈 이벤트 수신.
        event_type: 'I' = 편입, 'D' = 이탈
        """
        try:
            condition_name = condition_name.encode('latin-1').decode('cp949')
        except Exception:
            pass
        action = '편입' if event_type == 'I' else '이탈'
        print(f"[Kiwoom] 실시간 조건: '{condition_name}' → {code} {action}")
        if self._real_condition_cb:
            self._real_condition_cb(code, action, condition_name)

    def connect(self):
        ret = self.api.dynamicCall("CommConnect()")
        print(f"[Kiwoom] CommConnect 호출: {ret}")
        return ret

    def get_state(self):
        return self.api.dynamicCall("GetConnectState()")

    def request_price(self, code, screen="0101"):
        """KRX 기준 주식 기본정보 TR 요청 (opt10001)"""
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드", code])
        self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opt10001_req", "opt10001", 0, screen]
        )

    def request_nxt_price(self, code, screen="0102"):
        """
        NXT 기준 주식 기본정보 TR 요청.

        NXT 전용 시간대(08:00~09:00, 15:30~20:00)에 호출합니다.
        키움 OpenAPI에서 NXT 시세는 opt10001을 사용하되
        스크린 번호를 구분하여 요청합니다.

        ※ 키움 NXT API 정식 TR 코드가 별도로 공개되면
           해당 TR로 교체가 필요할 수 있습니다.
        """
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드", code])
        self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opt10001_nxt_req", "opt10001", 0, screen]
        )

    def request_holdings(self, account_no):
        """계좌 보유종목 TR 요청 (opw00018 우선, 실패시 OPW00004 fallback)"""
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["계좌번호",             account_no])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호",             ""])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호입력매체구분", "00"])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["조회구분",             "1"])
        ret = self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opw00018_req", "opw00018", 0, "0150"]
        )
        print(f"[Kiwoom] CommRqData(opw00018) 반환값: {ret}")
        if ret < 0:
            print(f"[Kiwoom] opw00018 실패(ret={ret}) → OPW00004 재시도")
            self.api.dynamicCall("SetInputValue(QString, QString)", ["계좌번호",             account_no])
            self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호",             ""])
            self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호입력매체구분", "00"])
            self.api.dynamicCall("SetInputValue(QString, QString)", ["조회구분",             "1"])
            ret2 = self.api.dynamicCall(
                "CommRqData(QString, QString, int, QString)",
                ["opw00004_req", "OPW00004", 0, "0151"]
            )
            print(f"[Kiwoom] CommRqData(OPW00004) 반환값: {ret2}")

    def request_daily_trades(self, account_no: str, screen="0160"):
        """계좌별 당일 체결현황 TR 요청 (opw00007) — 장중에만 유효"""
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["계좌번호",             account_no])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호",             ""])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호입력매체구분", "00"])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["조회구분",             "0"])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드",             ""])
        ret = self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opw00007_req", "opw00007", 0, screen]
        )
        print(f"[Kiwoom] CommRqData(opw00007) 반환값: {ret}")

    def request_realized_pnl(self, account_no: str, date_from: str, date_to: str, screen="0162"):
        """계좌별 실현손익 TR 요청 (opt10073) — 날짜: YYYYMMDD"""
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["계좌번호",             account_no])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호",             ""])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호입력매체구분", "00"])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["시작일자",             date_from])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종료일자",             date_to])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드",             ""])
        ret = self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opt10073_req", "opt10073", 0, screen]
        )
        print(f"[Kiwoom] CommRqData(opt10073) 반환값: {ret}")

    def request_period_trades(self, account_no: str, date_from: str, date_to: str, screen="0161"):
        """계좌 기간별 주문체결 내역 TR 요청 (opw00015) — 날짜: YYYYMMDD"""
        print(f"[Kiwoom] opw00015 요청 acct={account_no!r} from={date_from!r} to={date_to!r}")
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["계좌번호",             account_no])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호",             ""])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["비밀번호입력매체구분", "00"])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["조회구분",             "1"])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["시작일자",             date_from])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종료일자",             date_to])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드",             ""])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["매매구분",             ""])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["단가구분",             "1"])
        ret = self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opw00015_req", "opw00015", 0, screen]
        )
        print(f"[Kiwoom] CommRqData(opw00015) 반환값: {ret}")

    def request_investor_trend(self, code: str, screen="0110"):
        """
        OPT10059 — 주식투자자별매매동향 TR 요청.

        입력값:
          일자         : 조회 기준일 (오늘)
          종목코드     : 6자리 코드
          금액수량구분 : 1 = 금액(천원)
          매매구분     : 0 = 순매수
          단위구분     : 1000 = 천주

        반환 콜백: _on_tr_data('opt10059_req') → type='investor_trend'
        """
        self._tr_event.clear()
        self._tr_data = {}
        today = datetime.today().strftime("%Y%m%d")
        self.api.dynamicCall("SetInputValue(QString, QString)", ["일자",         today])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드",     code])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["금액수량구분", "1"])    # 금액
        self.api.dynamicCall("SetInputValue(QString, QString)", ["매매구분",     "0"])    # 순매수
        self.api.dynamicCall("SetInputValue(QString, QString)", ["단위구분",     "1000"]) # 천주
        self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opt10059_req", "opt10059", 0, screen]
        )

    def request_ohlcv(self, code: str, screen="0120"):
        """
        OPT10081 — 주식일봉차트조회 TR 요청.

        입력값:
          종목코드       : 6자리 코드
          기준일자       : 오늘 (조회 마지막 날)
          수정주가구분   : 1 = 수정주가 반영

        반환 콜백: _on_tr_data('opt10081_req') → type='ohlcv'
        """
        self._tr_event.clear()
        self._tr_data = {}
        today = datetime.today().strftime("%Y%m%d")
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드",     code])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["기준일자",     today])
        self.api.dynamicCall("SetInputValue(QString, QString)", ["수정주가구분", "1"])
        self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opt10081_req", "opt10081", 0, screen]
        )

    def request_futures_price(self, code: str, screen="0300"):
        """opt50001 — 선물시세조회. 단일 종목 현재가·등락율."""
        self._tr_event.clear()
        self._tr_data = {}
        self.api.dynamicCall("SetInputValue(QString, QString)", ["종목코드", code])
        self.api.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            ["opt50001_req", "opt50001", 0, screen]
        )

    def get_future_list(self):
        """KOSPI200 선물 코드 목록(최근월물 우선). GetFutureList()는 TR 아님, 즉시 반환."""
        try:
            raw = self.api.dynamicCall("GetFutureList()") or ""
            return [c.strip().split('^')[0] for c in raw.split(';') if c.strip()]
        except Exception:
            return []


# ══════════════════════════════════════════════════════
# ── 키움 워커 (Flask 싱글톤) ──
# ══════════════════════════════════════════════════════

class KiwoomWorker:
    """
    Flask에서 사용하는 싱글톤 키움 API 래퍼.
    Qt 이벤트 루프를 별도 스레드에서 실행하고
    Flask 요청 스레드와 안전하게 통신함.
    """

    _instance = None
    _lock     = threading.Lock()

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
        self._ready   = threading.Event()
        self._api     = None
        self._app     = None
        self._api_lock = threading.Lock()
        self._theme_index_cache = None   # {code: [theme_info, ...]}
        self._deposit_cache     = None   # 마지막 보유종목 조회 시 추출한 예수금

        t = threading.Thread(target=self._run_qt, daemon=True)
        t.start()
        self._ready.wait(timeout=10)
        print("[Kiwoom] Worker 초기화 완료")

    def _run_qt(self):
        self._app = QApplication.instance() or QApplication(sys.argv)
        try:
            self._api = KiwoomAPI()
            self._api.api.setFixedSize(0, 0)
            self._api.api.show()
        except Exception as e:
            print(f"[Kiwoom] ⚠ COM 컨트롤 초기화 실패 (64비트 Python 또는 미설치): {e}")
            print("[Kiwoom] 키움 API 없이 서버를 계속 실행합니다.")
            self._api = None
        self._ready.set()
        self._app.exec_()

    def _process(self):
        if self._app:
            self._app.processEvents()

    def _wait_tr(self, timeout=5) -> bool:
        """
        TR 응답 대기.
        Flask 스레드에서 CommRqData 호출 시 COM 응답이 Flask 스레드 아파트먼트로 오므로
        processEvents()로 해당 스레드의 메시지 펌프를 직접 구동해야 콜백이 도착함.
        """
        start = time.time()
        while time.time() - start < timeout:
            self._process()
            if self._api._tr_event.is_set():
                return True
            time.sleep(0.1)
        return False

    def _parse_price_data(self, code: str, d: dict) -> dict:
        """TR 응답 딕셔너리 → 정제된 가격/재무 딕셔너리"""
        return {
            "code":          code,
            "name":          decode_kiwoom(d.get("종목명", code)),
            "price":         safe_int(d.get("현재가", 0)),
            "base_price":    safe_int(d.get("기준가", 0)),
            "change":        safe_signed_int(d.get("전일대비", 0)),
            "rate":          safe_float(d.get("등락율", 0)),
            "volume":        safe_int(d.get("거래량", 0)),
            "trade_amount":  safe_int(d.get("거래대금", 0)),
            "open":          safe_int(d.get("시가", 0)),
            "high":          safe_int(d.get("고가", 0)),
            "low":           safe_int(d.get("저가", 0)),
            "market_cap":    safe_int(d.get("시가총액", 0)),
            "per":           safe_float(d.get("PER", 0)),
            "pbr":           safe_float(d.get("PBR", 0)),
            "eps":           safe_signed_int(d.get("EPS", 0)),
            "bps":           safe_signed_int(d.get("BPS", 0)),
            "roe":           safe_float(d.get("ROE", 0)),
            "dividend":      safe_float(d.get("배당수익률", 0)),
            "week52_high":   safe_int(d.get("연중최고", 0)),
            "week52_low":    safe_int(d.get("연중최저", 0)),
            "foreign_ratio": safe_float(d.get("외국인소진율", 0)),
            "shares":        safe_int(d.get("상장주식수", 0)),
        }

    # ──────────────────────────────────────
    # 공개 메서드
    # ──────────────────────────────────────

    def get_login_state(self) -> int:
        if not self._api:
            return 0
        return self._api.get_state()

    def login(self, timeout=60) -> dict:
        if not self._api:
            msg = "COM 컨트롤 초기화 실패 — 32비트 Python(Python311-32)으로 실행해야 합니다."
            print(f"[Kiwoom] ⚠ {msg}")
            return {"success": False, "err_code": None, "msg": msg}
        if self.get_login_state() == 1:
            return {"success": True, "err_code": 0, "msg": "이미 로그인됨"}
        self._api._login_event.clear()
        self._api._login_result = None
        self._api._login_msg    = ""
        self._api.connect()
        threading.Thread(target=self._activate_login_popup, daemon=True).start()

        start = time.time()
        while time.time() - start < timeout:
            self._process()
            if self._api._login_event.is_set():
                break
            time.sleep(0.1)

        err_code = self._api._login_result
        msg      = getattr(self._api, '_login_msg', '') or f"err_code={err_code}"
        if err_code is None:
            msg = f"로그인 타임아웃 ({timeout}초 초과) — 팝업이 열렸는지 확인하세요."
        print(f"[Kiwoom] 로그인 결과: {err_code} — {msg}")
        return {"success": err_code == 0, "err_code": err_code, "msg": msg}

    def _activate_login_popup(self):
        # 키움 API 버전/언어에 따라 창 제목이 다를 수 있어 여러 후보를 시도
        _TITLES = [
            'Open API Login',
            'KHOpenAPI',
            '키움증권',
            '로그인',
            'Login',
        ]
        try:
            import win32gui
            for _ in range(60):          # 30초 탐색 (0.5초 × 60)
                time.sleep(0.5)
                for title in _TITLES:
                    hwnd = win32gui.FindWindow(None, title)
                    if hwnd:
                        win32gui.SetForegroundWindow(hwnd)
                        print(f"[Kiwoom] 로그인 팝업 활성화 완료 (창: '{title}')")
                        return
            print("[Kiwoom] 로그인 팝업을 찾지 못했습니다 — 자동 로그인 설정을 확인하거나 팝업을 직접 클릭하세요.")
        except ImportError:
            print("[Kiwoom] pywin32 미설치 — 팝업이 뜨면 직접 입력해주세요.")
        except Exception as e:
            print(f"[Kiwoom] 팝업 활성화 실패: {e}")

    def get_stock_price(self, code: str, timeout=5) -> dict | None:
        """
        KRX 기준 현재가 + 재무정보 조회 (opt10001).
        TR 속도 제한(초당 1건) 방지: 응답 후 0.4초 대기.
        _api_lock 으로 동시 TR 호출 방지 (COM 객체 단일스레드 안전)
        """
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                self._api._tr_event.clear()
                self._api.request_price(code)
                if not self._wait_tr(timeout) or not self._api._tr_data:
                    return None
                result = self._parse_price_data(code, self._api._tr_data)
                result["price_source"] = "KRX"
                time.sleep(0.4)
                return result
            except Exception as e:
                print(f"[Kiwoom] get_stock_price 오류: {e}")
                return None

    def get_nxt_price(self, code: str, timeout=5) -> dict | None:
        """
        NXT 기준 현재가 조회.

        NXT 전용 시간대(08:00~09:00, 15:30~20:00)에서
        KRX 종가 대신 NXT 실시간 가격을 반환합니다.

        ※ 키움 OpenAPI의 NXT 전용 TR이 별도로 공개되면
           request_nxt_price() 내부의 TR 코드를 업데이트하세요.
        """
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                self._api._tr_event.clear()
                self._api.request_nxt_price(code)
                if not self._wait_tr(timeout) or not self._api._tr_data:
                    return None
                result = self._parse_price_data(code, self._api._tr_data)
                result["price_source"] = "NXT"
                time.sleep(0.4)
                return result
            except Exception as e:
                print(f"[Kiwoom] get_nxt_price 오류: {e}")
                return None

    def get_best_price(self, code: str, timeout=5) -> dict | None:
        """
        현재 시장 세션에 따라 최적 가격을 자동 선택하여 반환합니다.

        세션별 동작:
        - CLOSED     : None 반환 (장 마감)
        - NXT_PRE    : NXT 시세 조회 (08:00~09:00)
        - BOTH       : KRX 시세 조회 (09:00~15:30, KRX 우선)
        - NXT_AFTER  : NXT 시세 조회 (15:30~20:00)
        """
        session = get_market_session()

        if not session["krx"] and not session["nxt"]:
            data = self.get_stock_price(code, timeout)
            if data:
                data.update({
                    "session":       session["session"],
                    "session_label": session["label"],
                    "price_source":  "KRX_CLOSE",
                })
            return data

        if session["krx"]:
            data = self.get_stock_price(code, timeout)
        else:
            data = self.get_nxt_price(code, timeout)
            if data is None:
                print(f"[Kiwoom] NXT 시세 실패 → KRX fallback: {code}")
                data = self.get_stock_price(code, timeout)

        if data:
            data.update({
                "session":       session["session"],
                "session_label": session["label"],
            })
        return data

    def get_stock_info(self, code: str, timeout=5) -> dict | None:
        """재무정보 조회 (get_stock_price 재사용, 추가 TR 없음)"""
        data = self.get_stock_price(code, timeout)
        if not data:
            return None
        return {
            "code":          data["code"],
            "name":          data["name"],
            "per":           data["per"],
            "pbr":           data["pbr"],
            "eps":           data["eps"],
            "bps":           data["bps"],
            "roe":           data["roe"],
            "market_cap":    data["market_cap"],
            "dividend":      data["dividend"],
            "week52_high":   data["week52_high"],
            "week52_low":    data["week52_low"],
            "foreign_ratio": data["foreign_ratio"],
            "shares":        data["shares"],
            "sector":        "-",
        }

    def get_account_no(self) -> str | None:
        if not self._api:
            return None
        if self._api._account_no:
            return self._api._account_no
        if self.get_login_state() != 1:
            return None

        print("[Kiwoom] 계좌번호 직접 조회 시도 중...")
        result_holder = [None]
        done = threading.Event()

        def fetch_account():
            try:
                raw = self._api.api.dynamicCall("GetLoginInfo(QString)", ["ACCNO"])
                accounts = [a for a in raw.split(';') if a.strip()]
                result_holder[0] = accounts[0] if accounts else None
                self._api._account_no = result_holder[0]
                print(f"[Kiwoom] 계좌번호 직접 조회 완료: {self._api._account_no}")
            except Exception as e:
                print(f"[Kiwoom] 계좌번호 직접 조회 실패: {e}")
            finally:
                done.set()

        QTimer.singleShot(0, fetch_account)
        start = time.time()
        while not done.is_set() and time.time() - start < 3:
            self._process()
            time.sleep(0.05)

        if not result_holder[0]:
            print("[Kiwoom] 계좌번호를 가져올 수 없습니다.")
        return result_holder[0]

    def get_account_holdings(self, timeout=10) -> list | None:
        """키움 실계좌 보유종목 조회 (opw00018). 부산물로 예수금을 _deposit_cache에 저장."""
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                account_no = self.get_account_no()
                if not account_no:
                    return None

                print(f"[Kiwoom] 계좌 보유종목 조회 시작: {account_no}")
                self._api._tr_event.clear()
                self._api.request_holdings(account_no)

                if not self._wait_tr(timeout):
                    print("[Kiwoom] 보유종목 TR 수신 실패")
                    return None

                data = self._api._tr_data
                if not data or data.get("type") != "holdings":
                    print("[Kiwoom] 보유종목 TR 수신 실패")
                    return None

                holdings = data.get("holdings", [])
                # opw00018 싱글 데이터에서 추출한 예수금 캐시
                self._deposit_cache = data.get("deposit")
                print(f"[Kiwoom] 보유종목 {len(holdings)}개, 예수금 {self._deposit_cache:,}원 조회 완료")
                return holdings
            except Exception as e:
                print(f"[Kiwoom] get_account_holdings 오류: {e}")
                return None

    def get_realized_pnl(self, date_from: str, date_to: str, timeout=15) -> dict | None:
        """계좌별 실현손익 조회 (opt10073). date: YYYYMMDD"""
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                account_no = self.get_account_no()
                if not account_no:
                    return None
                self._api._tr_event.clear()
                self._api.request_realized_pnl(account_no, date_from, date_to)
                if not self._wait_tr(timeout):
                    print("[Kiwoom] 실현손익 TR 수신 실패")
                    return None
                data = self._api._tr_data
                if not data or data.get("type") != "realized_pnl":
                    return None
                time.sleep(0.4)
                return data
            except Exception as e:
                print(f"[Kiwoom] get_realized_pnl 오류: {e}")
                return None

    def get_deposit(self) -> int | None:
        """마지막 보유종목 조회 시 캐시된 예수금 반환"""
        return getattr(self, '_deposit_cache', None)

    def get_period_trades(self, date_from: str, date_to: str, timeout=15) -> list | None:
        """계좌 기간별 주문체결 내역 조회 (opw00015). date: YYYYMMDD"""
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                account_no = self.get_account_no()
                if not account_no:
                    return None

                print(f"[Kiwoom] 기간 체결 조회: {date_from}~{date_to}")
                self._api._tr_event.clear()
                self._api.request_period_trades(account_no, date_from, date_to)
                if not self._wait_tr(timeout):
                    print("[Kiwoom] 기간 체결 TR 수신 실패")
                    return None
                data = self._api._tr_data
                trades = data.get("trades", []) if data and data.get("type") == "period_trades" else []
                print(f"[Kiwoom] 기간 체결 {len(trades)}건 완료")
                time.sleep(0.4)
                return trades
            except Exception as e:
                print(f"[Kiwoom] get_period_trades 오류: {e}")
                return None

    def get_daily_trades(self, timeout=10) -> list | None:
        """계좌별 당일 체결현황 조회 (opw00007)"""
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                account_no = self.get_account_no()
                if not account_no:
                    return None

                print(f"[Kiwoom] 당일 체결현황 조회 시작: {account_no}")
                self._api._tr_event.clear()
                self._api.request_daily_trades(account_no)

                if not self._wait_tr(timeout):
                    print("[Kiwoom] 당일 체결 TR 수신 실패")
                    return None

                data = self._api._tr_data
                if not data or data.get("type") != "daily_trades":
                    print("[Kiwoom] 당일 체결 TR 데이터 없음")
                    return []

                trades = data.get("trades", [])
                print(f"[Kiwoom] 당일 체결 {len(trades)}건 조회 완료")
                time.sleep(0.4)
                return trades
            except Exception as e:
                print(f"[Kiwoom] get_daily_trades 오류: {e}")
                return None

    # ──────────────────────────────────────
    # 투자자별 매매동향 (신규)
    # ──────────────────────────────────────

    def get_investor_trend(self, code: str, investor_type: str = "외국인",
                           count: int = 20, timeout: int = 10) -> list[float]:
        """
        OPT10059 — 주식투자자별매매동향 조회.

        Args:
            code          : 종목코드 (6자리)
            investor_type : "외국인" | "기관" | "개인"
            count         : 최근 몇 영업일 데이터 (기본 20일)
            timeout       : TR 대기 타임아웃 (초)

        Returns:
            list[float] — 날짜 오름차순(과거→최신) 순매수 금액 리스트.
            키움 TR은 최대 20행 반환. 실패 시 [0.0] * count 반환.

        Note:
            feature.py 의 calc_supply_features() 에서 z-score 계산에 사용.
            _api_lock 으로 동시 TR 직렬화.
        """
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return [0.0] * count

                self._api._tr_event.clear()
                self._api.request_investor_trend(code)

                if not self._wait_tr(timeout) or not self._api._tr_data:
                    print(f"[Kiwoom] get_investor_trend TR 수신 실패: {code}")
                    return [0.0] * count

                data = self._api._tr_data
                if data.get("type") != "investor_trend":
                    return [0.0] * count

                # 키움은 최신순으로 반환 → 오름차순(과거→최신)으로 reverse
                key_map = {"외국인": "foreign", "기관": "institution", "개인": "individual"}
                key     = key_map.get(investor_type, "foreign")
                rows    = data.get("rows", [])
                values  = [float(r.get(key, 0)) for r in reversed(rows[:count])]

                time.sleep(0.4)  # TR 속도 제한
                return values

            except Exception as e:
                print(f"[Kiwoom] get_investor_trend 오류 ({code}): {e}")
                return [0.0] * count

    def get_foreign_hold_ratio(self, code: str) -> float:
        """
        외국인 보유비율(%) 조회.
        opt10001(get_stock_price) 의 '외국인소진율' 필드를 재사용.
        별도 TR 없음 → 락 내부에서 한 번만 호출됨.

        Returns:
            float — 외국인 보유비율 (예: 55.32). 실패 시 0.0.
        """
        data = self.get_stock_price(code)
        if data:
            return float(data.get("foreign_ratio", 0.0))
        return 0.0

    # ──────────────────────────────────────
    # 선물 시세 (사이드카 선행신호)
    # ──────────────────────────────────────

    def get_futures_price(self, code: str, timeout: int = 10) -> dict | None:
        """KOSPI200 선물 현재가·등락율(%). 실패/이상치 시 None → 호출측 폴백."""
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return None
                self._api._tr_event.clear()
                self._api.request_futures_price(code)
                if not self._wait_tr(timeout) or not self._api._tr_data:
                    return None
                data = self._api._tr_data
                if data.get("type") != "futures":
                    return None
                price  = float(data.get("price") or 0)
                change = float(data.get("change") or 0)
                time.sleep(0.4)
                if price <= 0 or abs(change) > 30:   # 방어: 이상치면 폴백 유도
                    return None
                return {"price": price, "change": change, "code": code}
            except Exception as e:
                print(f"[Kiwoom] get_futures_price 오류 ({code}): {e}")
                return None

    def get_kospi200_front_code(self) -> str:
        """KOSPI200 선물 최근월물 코드. 실패 시 빈 문자열."""
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return ""
                codes = self._api.get_future_list()
                return codes[0] if codes else ""
            except Exception:
                return ""

    # ──────────────────────────────────────
    # 일봉 OHLCV 조회 (신규)
    # ──────────────────────────────────────

    def get_ohlcv(self, code: str, count: int = 80,
                  timeout: int = 10) -> pd.DataFrame:
        """
        OPT10081 — 주식일봉차트조회.

        Args:
            code    : 종목코드 (6자리)
            count   : 최근 몇 영업일 (기본 80일 → 기술적 지표 60일 + 여유분)
            timeout : TR 대기 타임아웃 (초)

        Returns:
            pd.DataFrame — columns=['open','high','low','close','volume'],
                           DatetimeIndex, 오름차순(과거→최신).
            실패 시 빈 DataFrame 반환.

        Note:
            키움 OPT10081은 한 번 요청으로 최대 600행 반환.
            signal.py 와 feature.py 가 이 메서드를 통해 OHLCV 를 받음.
        """
        with self._api_lock:
            try:
                if self.get_login_state() != 1:
                    return pd.DataFrame()

                self._api._tr_event.clear()
                self._api.request_ohlcv(code)

                if not self._wait_tr(timeout) or not self._api._tr_data:
                    print(f"[Kiwoom] get_ohlcv TR 수신 실패: {code}")
                    return pd.DataFrame()

                data = self._api._tr_data
                if data.get("type") != "ohlcv":
                    return pd.DataFrame()

                rows = data.get("rows", [])
                if not rows:
                    return pd.DataFrame()

                df = pd.DataFrame(rows)
                df["date"]  = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
                df          = df.dropna(subset=["date"])
                df          = df.set_index("date").sort_index()           # 오름차순
                df          = df[["open", "high", "low", "close", "volume"]].astype(float)
                df          = df.tail(count)                               # 최근 count 행만

                time.sleep(0.4)
                print(f"[Kiwoom] get_ohlcv 완료: {code} {len(df)}행")
                return df

            except Exception as e:
                print(f"[Kiwoom] get_ohlcv 오류 ({code}): {e}")
                return pd.DataFrame()

    # ──────────────────────────────────────
    # 조건검색
    # ──────────────────────────────────────

    def load_condition_list(self, timeout=10) -> dict:
        """
        HTS에 저장된 조건식 목록을 불러옵니다.
        반환: {'조건명A': 0, '조건명B': 1, ...}

        ※ 이 메서드를 먼저 호출해야 run_condition()이 작동합니다.
        ※ 키움 HTS(영웅문)에 조건식이 미리 저장되어 있어야 합니다.

        올바른 순서:
          1) GetConditionLoad()  → OnReceiveConditionVer 콜백 트리거
          2) 콜백 내부에서 GetConditionNameList() 로 파싱
        """
        if self.get_login_state() != 1:
            print("[Kiwoom] 조건검색 목록 로드 실패: 로그인 필요")
            return {}

        self._api._condition_event.clear()
        self._api._condition_list = {}

        ret = self._api.api.dynamicCall("GetConditionLoad()")
        print(f"[Kiwoom] GetConditionLoad 호출: ret={ret}")

        start = time.time()
        while time.time() - start < timeout:
            self._process()
            if self._api._condition_event.is_set():
                break
            time.sleep(0.1)

        if not self._api._condition_list:
            print("[Kiwoom] 조건식 목록이 비어있습니다. HTS(영웅문)에 조건식을 저장했는지 확인하세요.")

        return self._api._condition_list

    def run_condition(self, condition_name: str, timeout=15) -> list:
        """
        특정 조건식으로 종목 검색을 실행합니다.

        반환: ['005930', '000660', ...] 종목코드 리스트 (빈 리스트 = 결과 없음 or 실패)

        Args:
            condition_name: HTS에서 만든 조건식 이름 (정확히 일치해야 함)
        """
        if self.get_login_state() != 1:
            return []

        if not self._api._condition_list:
            self.load_condition_list()

        condition_index = self._api._condition_list.get(condition_name)
        if condition_index is None:
            avail = list(self._api._condition_list.keys())
            print(f"[Kiwoom] 조건식 '{condition_name}' 없음. 사용 가능: {avail}")
            return []

        self._api._condition_event.clear()
        self._api._condition_result = []

        ret = self._api.api.dynamicCall(
            "SendCondition(QString, QString, int, int)",
            ["0200", condition_name, condition_index, 0]
        )
        if ret != 1:
            print(f"[Kiwoom] SendCondition 실패 (ret={ret})")
            return []

        start = time.time()
        while time.time() - start < timeout:
            self._process()
            if self._api._condition_event.is_set():
                break
            time.sleep(0.1)

        return self._api._condition_result

    def start_real_condition(self, condition_name: str, callback=None) -> bool:
        """
        실시간 조건검색을 등록합니다.
        이후 종목 편입/이탈 시 callback(code, action, condition_name) 이 호출됩니다.
        """
        if self.get_login_state() != 1:
            return False

        if not self._api._condition_list:
            self.load_condition_list()

        condition_index = self._api._condition_list.get(condition_name)
        if condition_index is None:
            return False

        if callback:
            self._api._real_condition_cb = callback

        ret = self._api.api.dynamicCall(
            "SendCondition(QString, QString, int, int)",
            ["0201", condition_name, condition_index, 1]
        )
        success = (ret == 1)
        if success:
            print(f"[Kiwoom] 실시간 조건검색 등록: '{condition_name}'")
        return success

    def stop_real_condition(self, condition_name: str):
        """실시간 조건검색 등록을 해제합니다."""
        if not self._api._condition_list:
            return
        condition_index = self._api._condition_list.get(condition_name)
        if condition_index is None:
            return
        self._api.api.dynamicCall(
            "SendConditionStop(QString, QString, int)",
            ["0201", condition_name, condition_index]
        )
        self._api._real_condition_cb = None
        print(f"[Kiwoom] 실시간 조건검색 해제: '{condition_name}'")

    # ──────────────────────────────────────
    # 테마 검색
    # ──────────────────────────────────────

    def get_theme_list(self, sort: int = 0) -> list:
        """
        키움 HTS 테마 목록. (TR 없이 직접 호출 — 락 불필요)
        반환 형식: "코드|테마명;코드|테마명;..."
        """
        if self.get_login_state() != 1:
            return []
        try:
            raw = self._api.api.dynamicCall("GetThemeGroupList(int)", [sort])
            if not raw:
                return []
            # COM 반환값이 CP949 바이트를 latin-1로 잘못 디코딩한 경우 복원
            try:
                raw = raw.encode('latin-1').decode('cp949')
            except Exception:
                pass
            themes = []
            for item in raw.split(';'):
                item = item.strip()
                if not item:
                    continue
                parts = item.split('|')
                if len(parts) < 2:
                    continue
                theme_code = parts[0].strip()
                theme_name = parts[1].strip()
                rate = float(parts[2].strip()) if len(parts) > 2 else 0.0
                if theme_code and theme_name:
                    themes.append({"theme_code": theme_code,
                                   "theme_name": theme_name, "rate": rate})
            print(f"[Kiwoom] 테마 목록: {len(themes)}개")
            return themes
        except Exception as e:
            print(f"[Kiwoom] get_theme_list 오류: {e}")
            return []

    def get_theme_stocks(self, theme_code: str) -> list:
        """특정 테마 종목코드 목록. (TR 없이 직접 호출 — 락 불필요)"""
        if self.get_login_state() != 1:
            return []
        try:
            raw = self._api.api.dynamicCall("GetThemeGroupCode(QString)", [theme_code])
            if not raw:
                return []
            codes = []
            for c in raw.split(';'):
                c = c.strip().lstrip('A')
                if c and c.isdigit() and len(c) == 6:
                    codes.append(c)
            print(f"[Kiwoom] 테마 '{theme_code}' 종목: {len(codes)}개")
            return codes
        except Exception as e:
            print(f"[Kiwoom] get_theme_stocks 오류: {e}")
            return []

    def build_theme_index(self, force=False) -> dict:
        """
        전체 테마→종목 역방향 인덱스를 한 번에 빌드해 캐싱합니다.
        {종목코드: [{"theme_code": ..., "theme_name": ..., "rate": ...}, ...]}

        force=True 이면 캐시를 무시하고 재빌드.
        """
        if self._theme_index_cache is not None and not force:
            return self._theme_index_cache

        if self.get_login_state() != 1:
            return {}

        print("[Kiwoom] 테마 인덱스 빌드 시작...")
        all_themes = self.get_theme_list(0)
        if not all_themes:
            print("[Kiwoom] 테마 목록 없음 — 인덱스 빌드 실패")
            return {}

        index = {}
        ok = 0
        for theme in all_themes:
            try:
                raw = self._api.api.dynamicCall(
                    "GetThemeGroupCode(QString)", [theme['theme_code']]
                )
                if not raw:
                    continue
                for c in raw.split(';'):
                    c = c.strip().lstrip('A')
                    if c and c.isdigit() and len(c) == 6:
                        index.setdefault(c, []).append({
                            "theme_code": theme['theme_code'],
                            "theme_name": theme['theme_name'],
                            "rate":       theme.get('rate', 0),
                        })
                ok += 1
            except Exception as e:
                print(f"[Kiwoom] 테마 '{theme['theme_code']}' 인덱스 오류: {e}")

        self._theme_index_cache = index
        total_codes = len(index)
        print(f"[Kiwoom] 테마 인덱스 빌드 완료: {ok}/{len(all_themes)}개 테마, {total_codes}개 종목")
        return index


# ── 싱글톤 인스턴스 ──
kiwoom = KiwoomWorker()