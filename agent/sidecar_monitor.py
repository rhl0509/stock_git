"""
agent/sidecar_monitor.py
========================
코스피 변동을 '단계 × 시간창 × 방향'으로 세분화해 감지하고,
방향에 맞는 외국인·기관 수급 종목을 포착하는 에이전트.

세분화 축 (방법 A — 추가 데이터원 없이 기존 부품만 사용):
  1) 시간창: 전일대비 · 개장후누적 · 5분 · 3분 · 1분 낙폭/상승폭을 각각 계산
     (네이버 실시간 KOSPI + 프로세스 내 분 단위 가격 이력)
  2) 단계(KRX 시장조치 근사): 관심→주의(사이드카)→경계(CB1)→위험(CB2)→비상(CB3).
     여러 시간창 중 '최고 심각도'를 그 시점의 단계로 채택.
  3) 방향: 하락(매도압력)→외국인·기관 동시 '순매수'(저가매수) 스캔,
           상승(매수압력)→외국인·기관 동시 '순매도'(차익실현) 스캔.

알림 정책:
  - 관심(1단계): 이벤트 기록만(알림·스캔 없음)
  - 주의 이상(2~5단계): 수급 스캔 + 텔레그램 알림
  - 같은 방향에서 '더 높은 단계'로 올라설 때만 알림(에스컬레이션, 단계별 1회/일)

실제 매도 사이드카는 'KOSPI200 선물 ±5%/1분', 서킷브레이커는 '현물 ±8/15/20%'.
선물 실시간 피드가 없어 현물 지수 기반으로 근사한다(=유사 국면).

스케줄: 평일 09:01~15:20 매 분 (agent/scheduler.py 의 _job_sidecar)
수동:   python -m agent.sidecar_monitor            # 현재 단계 평가만
        python -m agent.sidecar_monitor --force    # 트리거 무시하고 즉시 스캔(검증용)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from agent.data_collector import APP_BASE_URL
from agent.llm_client import generate

logger = logging.getLogger(__name__)

# ── 설정 (env 로 조정 가능) ─────────────────────────────────────────
MAX_SCAN     = int(os.getenv("SIDECAR_MAX_SCAN", "200"))          # 스캔 종목 수 상한
TOP_N        = int(os.getenv("SIDECAR_TOP_N", "12"))              # 결과 상위 N
SCAN_LEVEL   = int(os.getenv("SIDECAR_SCAN_LEVEL", "2"))          # 이 단계 이상에서 수급 스캔+알림

# Layer 2: 장중 급락 '속도' 선행 경보 — 사이드카(-5%) 도달 전에 먼저 알린다.
# 레벨(절대 낙폭)이 아니라 단기 낙폭 '속도'를 보므로 -5% 전에 탈출 시간을 준다.
VELO_1M = float(os.getenv("SIDECAR_VELO_1M", "-1.0"))            # 1분 낙폭 임계(%)
VELO_3M = float(os.getenv("SIDECAR_VELO_3M", "-1.8"))            # 3분 낙폭 임계(%)

# OPT10059 순매수 금액 원시값 → 억원 환산 제수 (백만원 단위, 라이브 실측 검증).
NET_DIV_TO_EOK = float(os.getenv("SIDECAR_NET_DIV_EOK", "100"))

# 트리거 기초지수: 사이드카(선물)·서킷브레이커가 정의된 '코스피200'(KPI200)을 기본 사용.
# 광범위 KOSPI(약 900종목)보다 정확. 조회 실패 시 KOSPI로 폴백.
INDEX_NAME = os.getenv("SIDECAR_INDEX", "KPI200")

# 선물 선행신호: 키움 KOSPI200 선물 실시간을 1순위로 사용(현물보다 선행).
# 미로그인/권한없음/이상치면 자동으로 현물(KPI200)로 폴백한다. 0/false 로 끄기.
USE_FUTURES = os.getenv("SIDECAR_USE_FUTURES", "1").lower() not in ("0", "false", "no")

# ── 단계 정의 (심각도 1~5) ──────────────────────────────────────────
LEVEL_NAME = {0: "정상", 1: "관심", 2: "주의", 3: "경계", 4: "위험", 5: "비상"}
LEVEL_DESC = {
    1: "변동성 확대",
    2: "사이드카 유사",
    3: "서킷브레이커 1단계 유사",
    4: "서킷브레이커 2단계 유사",
    5: "서킷브레이커 3단계 유사",
}
LEVEL_EMOJI_DOWN = {1: "👀", 2: "🛡️", 3: "⚠️", 4: "🚨", 5: "🆘"}
LEVEL_EMOJI_UP   = {1: "👀", 2: "🔺", 3: "📈", 4: "🚀", 5: "🆘"}

# ── 시간창별 임계 (단계, |등락률%|) 내림차순. 절대값 기준, 방향은 별도 판정 ──
#   전일대비·개장후: KRX 사다리 그대로(±1.5/3/8/15/20).
#   단기창(1·3·5분): 짧은 시간의 급변은 같은 %라도 더 심각 → 낮은 임계로 주의/경계.
_DAY_LADDER = [(5, 20.0), (4, 15.0), (3, 8.0), (2, 3.0), (1, 1.5)]
WINDOWS: list[tuple[str, str, int, list]] = [
    # (key, label, lookback_minutes(0=전일대비/None은 개장후), thresholds)
    ("day",  "전일대비", 0,  _DAY_LADDER),
    ("open", "개장후",  -1, _DAY_LADDER),
    ("5m",   "5분",    5,  [(3, 5.0), (2, 3.0)]),
    ("3m",   "3분",    3,  [(3, 4.0), (2, 2.5)]),
    ("1m",   "1분",    1,  [(3, 3.0), (2, 1.5)]),
]

# ── 모듈 상태 (프로세스 내 분 단위 호출에서 유지) ──────────────────
_price_hist: list[tuple] = []                       # [(datetime, price)] 최근 ~12분
_open_info: dict = {"date": None, "price": None}    # 당일 개장(첫 관측) 가격
_alerted: dict = {"date": None, "down": 0, "up": 0}  # 방향별 당일 최고 알림 단계
_velo_fired_date: str | None = None                  # 속도 선행 경보 당일 1회 제한
_universe_cache: dict = {"date": None, "codes": []}


# ─────────────────────────────────────────────────────────────────
# 지수 읽기 + 시간창/단계 평가
# ─────────────────────────────────────────────────────────────────

def _read_futures() -> dict | None:
    """키움 KOSPI200 선물 실시간 현재가·등락율(선행신호). 실패/이상치 시 None → 현물 폴백."""
    if not USE_FUTURES:
        return None
    try:
        from kiwoom_client import kiwoom
        d = kiwoom.get_futures_price()   # code=None → 콜렉터가 최근월물 자동 선택
        if d and d.get("price") and abs(float(d.get("change") or 0)) <= 30:
            return {"price": float(d["price"]), "change": float(d["change"]),
                    "as_of": "", "status": "OPEN", "source": "선물"}
    except Exception:
        pass
    return None


def _read_index() -> dict | None:
    """트리거 기초값 실시간 조회. 우선순위:
    1) 키움 KOSPI200 선물(선행) → 2) 네이버 코스피200 현물(KPI200) → 3) 광범위 KOSPI."""
    fut = _read_futures()
    if fut:
        return fut
    try:
        from agent.market_tools import _naver_index
        nv = _naver_index(INDEX_NAME)
        if nv and nv.get("price"):
            nv["source"] = "코스피200"
            return nv
        kospi = _naver_index("KOSPI")
        if kospi:
            kospi["source"] = "KOSPI"
        return kospi
    except Exception as e:
        logger.warning(f"[sidecar] 지수 조회 실패: {e}")
        return None


def _window_move(now: datetime, price: float, minutes: int) -> float | None:
    """가격 이력에서 minutes분 전 대비 등락률(%). 이력 부족 시 None."""
    target = now - timedelta(minutes=minutes)
    older = [p for (t, p) in _price_hist if t <= target and p > 0]
    if not older:
        return None
    base = older[-1]                       # target 보다 오래된 것 중 가장 최근
    return (price - base) / base * 100.0


def _level_for(thresholds: list, magnitude: float) -> int:
    """|등락률| 에 해당하는 최고 단계. 없으면 0."""
    for lvl, thr in thresholds:            # 내림차순
        if magnitude >= thr:
            return lvl
    return 0


def _eval_trigger(now: datetime) -> dict:
    """현재 지수를 읽어 시간창별 등락률·최고 단계·방향을 산출. 가격이력/개장가 갱신."""
    global _price_hist, _open_info
    nv = _read_index()
    if not nv or not nv.get("price"):
        return {"level": 0, "index": None}

    price  = float(nv["price"])
    change = nv.get("change")              # 전일대비 등락률(%) — None 가능
    date_str = now.strftime("%Y%m%d")

    # 개장(첫 관측) 가격 — 당일 첫 호출 시 기록
    if _open_info.get("date") != date_str:
        _open_info = {"date": date_str, "price": price}

    # 가격 이력 갱신 (최근 12분만 유지)
    _price_hist.append((now, price))
    cutoff = now - timedelta(minutes=12)
    _price_hist = [(t, p) for (t, p) in _price_hist if t >= cutoff]

    # 시간창별 등락률 계산
    moves: dict[str, float | None] = {}
    for key, _label, lookback, _thr in WINDOWS:
        if key == "day":
            moves[key] = float(change) if change is not None else None
        elif key == "open":
            op = _open_info.get("price")
            moves[key] = (price - op) / op * 100.0 if op else None
        else:
            moves[key] = _window_move(now, price, lookback)

    # 각 시간창 단계 평가 → 최고 단계 채택 (동률이면 |등락률| 큰 창)
    best = {"level": 0, "key": None, "label": None, "move": 0.0}
    for key, label, _lookback, thr in WINDOWS:
        mv = moves.get(key)
        if mv is None:
            continue
        lvl = _level_for(thr, abs(mv))
        if lvl > best["level"] or (lvl == best["level"] and lvl > 0 and abs(mv) > abs(best["move"])):
            best = {"level": lvl, "key": key, "label": label, "move": mv}

    direction = None
    if best["level"] > 0:
        direction = "down" if best["move"] < 0 else "up"

    return {
        "level":       best["level"],
        "level_name":  LEVEL_NAME.get(best["level"], "?"),
        "level_desc":  LEVEL_DESC.get(best["level"], ""),
        "direction":   direction,
        "window":      best["label"],
        "window_key":  best["key"],
        "window_move": best["move"],
        "index":       price,
        "change":      change,
        "moves":       moves,
        "source":      nv.get("source", ""),
        "as_of":       nv.get("as_of"),
        "status":      nv.get("status"),
    }


def _moves_line(moves: dict) -> str:
    """시간창 등락률을 사람이 읽는 한 줄로."""
    parts = []
    for key, label, _lb, _thr in WINDOWS:
        mv = moves.get(key)
        if mv is not None:
            parts.append(f"{label} {mv:+.2f}%")
    return " · ".join(parts)


# ─────────────────────────────────────────────────────────────────
# 종목 유니버스 / 이름
# ─────────────────────────────────────────────────────────────────

def _kospi200_codes(date_str: str) -> list[str]:
    """스캔 유니버스(코드 리스트). 하루 캐시.
    1순위 pykrx KOSPI200 구성종목(KRX 로그인 필요) → 2순위 FDR 시총 상위 KOSPI 대형주.
    ※ 어느 쪽이든 '리스트'만 확보할 뿐 수급은 키움 OPT10059 로 별도 조회한다."""
    if _universe_cache["date"] == date_str and _universe_cache["codes"]:
        return _universe_cache["codes"]

    codes: list[str] = []
    # 1순위: pykrx KOSPI200 (KRX_ID/KRX_PW 환경변수가 있을 때만 성공)
    try:
        from pykrx import stock as px
        codes = [str(c).zfill(6) for c in (px.get_index_portfolio_deposit_file("1028") or [])]
    except Exception as e:
        logger.info(f"[sidecar] pykrx KOSPI200 미사용({e}) → FDR 시총상위로 대체")

    # 2순위: FinanceDataReader 시가총액 상위 KOSPI 대형주(KRX 로그인 불필요)
    if not codes:
        try:
            import FinanceDataReader as fdr
            df = fdr.StockListing("KOSPI")
            if df is not None and not df.empty and "Marcap" in df.columns:
                df = df.dropna(subset=["Marcap"]).sort_values("Marcap", ascending=False)
                # 우선주 제외(KOSPI200은 보통주 기준): 코드 끝자리 0(보통주)만,
                # 종목명 끝 '우'/'우B' 제거. ETF/리츠 등은 시총상위 200에 거의 없음.
                rows = [(str(c).zfill(6), str(n)) for c, n in zip(df["Code"], df["Name"])]
                codes = [c for c, n in rows
                         if c.endswith("0") and not n.endswith("우") and not n.endswith("우B")]
                codes = codes[:MAX_SCAN]
        except Exception as e:
            logger.warning(f"[sidecar] FDR 유니버스 조회 실패: {e}")

    if codes:
        _universe_cache.update({"date": date_str, "codes": codes})
    return codes


def _name_map() -> dict[str, str]:
    """kr_stocks DB 에서 코드→종목명 매핑."""
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT code, name FROM kr_stocks")
                rows = cur.fetchall() or []
        finally:
            conn.close()
        return {str(r["code"]).zfill(6): r["name"] for r in rows}
    except Exception as e:
        logger.warning(f"[sidecar] 종목명 매핑 실패: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────
# 수급 스캔 (방향 인지)
# ─────────────────────────────────────────────────────────────────

def _today_net(code: str, investor_type: str) -> float | None:
    """키움 OPT10059 장중 누적 잠정 순매수(백만원). 당일(=리스트 마지막) 값. 실패 시 None."""
    try:
        from kiwoom_client import kiwoom
        vals = kiwoom.get_investor_trend(code, investor_type=investor_type, count=2)
        if not vals:
            return None
        return float(vals[-1])   # 오름차순(과거→최신) → 마지막이 당일 잠정치
    except Exception:
        return None


def _scan_flows(codes: list[str], want_buy: bool) -> list[dict]:
    """외국인·기관이 '동시에 같은 방향'인 종목 추출.
    want_buy=True  → 둘 다 순매수>0 (하락장 저가매수)
    want_buy=False → 둘 다 순매도<0 (상승장 차익실현)
    1차 외국인 부호 필터 → 생존 종목만 2차 기관 확인."""
    names = _name_map()

    def _match(v: float | None) -> bool:
        return v is not None and (v > 0 if want_buy else v < 0)

    # 1차: 외국인 부호 필터
    survivors: list[dict] = []
    for code in codes[:MAX_SCAN]:
        code = str(code).zfill(6)
        f_net = _today_net(code, "외국인")
        if _match(f_net):
            survivors.append({"code": code, "name": names.get(code, code), "foreign_net": f_net})

    # 2차: 생존 종목만 기관 확인 (둘 다 같은 방향)
    results: list[dict] = []
    for s in survivors:
        i_net = _today_net(s["code"], "기관")
        if _match(i_net):
            s["inst_net"] = i_net
            s["combined"] = s["foreign_net"] + i_net
            results.append(s)

    # 매수면 큰 순매수 우선(내림차순), 매도면 큰 순매도 우선(오름차순)
    results.sort(key=lambda x: x["combined"], reverse=want_buy)
    return results[:TOP_N]


# ─────────────────────────────────────────────────────────────────
# 알림 / 저장
# ─────────────────────────────────────────────────────────────────

def _arm_stops() -> int:
    """보유종목 손절가 자동 등록/점검(무발송). 반환: 변경 건수."""
    try:
        from agent.auto_stop_alert import run as _run_stop
        r = _run_stop(send_kakao=False)
        return int(r.get("created", 0)) + int(r.get("updated", 0))
    except Exception as e:
        logger.warning(f"[sidecar] 손절 자동등록 실패: {e}")
        return 0


def _send_velocity_alert(trig: dict, now: datetime):
    """Layer 2 — 급락 '속도' 선행 경보 + 손절가 자동 무장. 풀스캔 없이 즉시 발송."""
    armed = _arm_stops()
    moves = trig.get("moves", {})
    speed = []
    for key, label in (("1m", "1분"), ("3m", "3분"), ("5m", "5분")):
        mv = moves.get(key)
        if mv is not None:
            speed.append(f"{label} {mv:+.2f}%")
    lines = [
        f"⚡ 코스피 급락 '가속' — 매도 사이드카(-5%) 선행 경보 ({now.strftime('%H:%M')})",
        f"{trig.get('source') or '지수'} {trig.get('index'):,.2f} ({trig.get('change'):+.2f}%) · " + " · ".join(speed),
        "현 낙폭 속도가 지속되면 사이드카 발동 가능. 지금 보유종목 손절가를 점검하세요.",
    ]
    if armed:
        lines.append(f"🛡 손절가 자동 점검·등록 {armed}건 완료.")
    try:
        from notify.send import send_message_to_self
        send_message_to_self("\n".join(lines)[:1000],
                             link_url=f"{APP_BASE_URL}/price_alert", ai_generated=True)
        logger.info(f"[sidecar] 속도 선행 경보 발송 (armed={armed})")
    except Exception as e:
        logger.warning(f"[sidecar] 속도 경보 발송 실패: {e}")


def _eok(v: float) -> float:
    """원시 순매수액 → 억원 환산."""
    return v / NET_DIV_TO_EOK


def _build_prompt(stocks: list[dict], trig: dict) -> str:
    want_buy = trig.get("direction") != "up"
    act = "동시 순매수(저가매수)" if want_buy else "동시 순매도(차익실현)"
    persp = "역발상 저가매수" if want_buy else "차익실현/경계"
    lines = [f"  {i+1}. {s['name']}({s['code']}) "
             f"외국인 {_eok(s['foreign_net']):+,.0f}억 / 기관 {_eok(s['inst_net']):+,.0f}억"
             for i, s in enumerate(stocks)]
    arrow = "급락" if want_buy else "급등"
    return (f"코스피 {arrow}([{trig.get('level_name')}·{trig.get('level_desc')}], "
            f"{trig.get('window')} {trig.get('window_move'):+.2f}%) 국면에서 "
            f"외국인·기관이 {act} 중인 종목:\n\n"
            + "".join(l + "\n" for l in lines)
            + f"\n3문장 이내로: 1) 집중 섹터/테마 2) {persp} 관점에서의 의미")


def _send(stocks: list[dict], trig: dict, now: datetime):
    want_buy = trig.get("direction") != "up"
    level = trig.get("level", 2)
    emoji = (LEVEL_EMOJI_DOWN if want_buy else LEVEL_EMOJI_UP).get(level, "🛡️")
    arrow = "급락" if want_buy else "급등"
    act   = "동시 순매수(저가매수)" if want_buy else "동시 순매도(차익실현)"

    head = f"{emoji} [{trig.get('level_name')}·{trig.get('level_desc')}] 코스피 {arrow} — {now.strftime('%H:%M')}"
    sub  = f"{trig.get('source') or '지수'} {trig.get('index'):,.2f} ({trig.get('change'):+.2f}%) · 트리거: {trig.get('window')} {trig.get('window_move'):+.2f}%"
    brk  = "변동: " + _moves_line(trig.get("moves", {}))
    lines = [head, sub, brk, "─" * 20, f"외국인·기관 {act} 상위(잠정·억원):"]
    for s in stocks[:8]:
        lines.append(f"{s['name']}: 외 {_eok(s['foreign_net']):+,.0f}억 / 기 {_eok(s['inst_net']):+,.0f}억")

    commentary = ""
    try:
        commentary = generate(_build_prompt(stocks, trig), temperature=0.3, max_tokens=400) or ""
    except Exception as e:
        logger.warning(f"[sidecar] LLM 코멘트 실패: {e}")
    if commentary:
        lines += ["", commentary[:300]]

    msg = "\n".join(lines)[:1200]
    try:
        from notify.send import send_message_to_self
        send_message_to_self(msg, link_url=f"{APP_BASE_URL}/stock_live", ai_generated=True)
        logger.info(f"[sidecar] 알림 발송 완료 (L{level}/{trig.get('direction')}, {len(stocks)}건)")
    except Exception as e:
        logger.warning(f"[sidecar] 알림 발송 실패: {e}")


def _ensure_table():
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kospi_sidecar_events (
                        id             INT AUTO_INCREMENT PRIMARY KEY,
                        detected_at    DATETIME NOT NULL,
                        kospi_index    DECIMAL(10,2),
                        kospi_change   DECIMAL(6,2),
                        trigger_reason VARCHAR(60),
                        stocks_found   INT,
                        top_stocks     JSON,
                        created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_detected (detected_at DESC)
                    ) CHARACTER SET utf8mb4
                """)
            # 세분화 컬럼 추가 (기존 테이블이면 ALTER, 이미 있으면 무시)
            for ddl in (
                "ALTER TABLE kospi_sidecar_events ADD COLUMN level INT",
                "ALTER TABLE kospi_sidecar_events ADD COLUMN level_name VARCHAR(20)",
                "ALTER TABLE kospi_sidecar_events ADD COLUMN direction VARCHAR(8)",
                "ALTER TABLE kospi_sidecar_events ADD COLUMN trigger_window VARCHAR(20)",
            ):
                try:
                    with conn.cursor() as cur:
                        cur.execute(ddl)
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[sidecar] 테이블 초기화 실패: {e}")


def _save_event(stocks: list[dict], trig: dict, now: datetime):
    reason = f"{trig.get('window')} {trig.get('window_move'):+.2f}%"
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO kospi_sidecar_events
                       (detected_at, kospi_index, kospi_change, trigger_reason, stocks_found,
                        top_stocks, level, level_name, direction, trigger_window)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (now, trig.get("index"), trig.get("change"), reason, len(stocks),
                     json.dumps(stocks, ensure_ascii=False), trig.get("level"),
                     trig.get("level_name"), trig.get("direction"), trig.get("window")),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[sidecar] 이벤트 저장 실패: {e}")


# ─────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────

def _do_scan(send_kakao: bool, trig: dict, now: datetime) -> dict:
    """방향에 맞는 수급 스캔 + 발송 + 저장."""
    _ensure_table()
    date_str = now.strftime("%Y%m%d")
    want_buy = trig.get("direction") != "up"

    # 키움 콜렉터 로그인 확인
    try:
        from kiwoom_client import kiwoom
        if kiwoom.get_login_state() != 1:
            logger.warning("[sidecar] 키움 콜렉터 미로그인 — 스캔 불가")
            return {"ok": False, "triggered": True, "level": trig.get("level"),
                    "error": "kiwoom_not_logged_in"}
    except Exception as e:
        return {"ok": False, "triggered": True, "error": str(e)}

    codes = _kospi200_codes(date_str)
    if not codes:
        return {"ok": False, "triggered": True, "error": "no_universe"}

    logger.info(f"[sidecar] 스캔 시작: L{trig.get('level')}({trig.get('level_name')})/"
                f"{trig.get('direction')}, {len(codes[:MAX_SCAN])}종목")
    stocks = _scan_flows(codes, want_buy)

    _save_event(stocks, trig, now)
    if stocks and send_kakao:
        _send(stocks, trig, now)

    act = "순매수" if want_buy else "순매도"
    logger.info(f"[sidecar] 완료: 외국인·기관 동시 {act} {len(stocks)}종목")
    return {"ok": True, "triggered": True, "level": trig.get("level"),
            "level_name": trig.get("level_name"), "direction": trig.get("direction"),
            "window": trig.get("window"), "window_move": round(trig.get("window_move", 0), 2),
            "index": trig.get("index"), "stocks": len(stocks),
            "top": [s["name"] for s in stocks[:8]]}


def check_and_scan(send_kakao: bool = True) -> dict:
    """평일 장중 매 분 호출되는 진입점. 속도 선행 경보 → 단계 평가 → 에스컬레이션."""
    global _alerted, _velo_fired_date
    now = datetime.now()
    if now.weekday() >= 5:
        return {"ok": True, "triggered": False, "skipped": "weekend"}

    # 감시 시간대: 09:01 ~ 15:20 (개장 직후·마감 직전 제외)
    hm = now.hour * 60 + now.minute
    if hm < 9 * 60 + 1 or hm > 15 * 60 + 20:
        return {"ok": True, "triggered": False, "skipped": "out_of_window"}

    date_str = now.strftime("%Y%m%d")
    trig = _eval_trigger(now)          # 가격이력은 항상 갱신됨
    moves = trig.get("moves", {})

    # ── Layer 2: 급락 '속도' 선행 경보 (레벨과 독립, 더 민감, 하루 1회) ──
    m1, m3 = moves.get("1m"), moves.get("3m")
    if (_velo_fired_date != date_str and
            ((m1 is not None and m1 <= VELO_1M) or (m3 is not None and m3 <= VELO_3M))):
        _velo_fired_date = date_str
        if send_kakao:
            _send_velocity_alert(trig, now)

    level = trig.get("level", 0)
    if level == 0:
        return {"ok": True, "triggered": False, "level": 0, "index": trig.get("index"),
                "moves": _moves_line(moves)}

    direction = trig["direction"]
    if _alerted.get("date") != date_str:
        _alerted = {"date": date_str, "down": 0, "up": 0}

    # 같은 방향에서 더 높은 단계로 올라설 때만 처리(에스컬레이션)
    if level <= _alerted.get(direction, 0):
        return {"ok": True, "triggered": False, "skipped": "no_escalation",
                "level": level, "direction": direction}
    _alerted[direction] = level

    # 관심(1단계): 기록만, 알림·스캔 없음
    if level < SCAN_LEVEL:
        _ensure_table()
        _save_event([], trig, now)
        logger.info(f"[sidecar] {trig['level_name']}({direction}) 기록 — {trig['window']} {trig['window_move']:+.2f}%")
        return {"ok": True, "triggered": True, "level": level, "direction": direction,
                "action": "record_only", "window": trig["window"]}

    # 주의 이상: 수급 스캔 + 알림
    return _do_scan(send_kakao, trig, now)


def run(send_kakao: bool = True, force: bool = False) -> dict:
    """수동/CLI 진입점. force=True 면 트리거를 무시하고 즉시 스캔."""
    now = datetime.now()
    if force:
        trig = _eval_trigger(now)
        if trig.get("level", 0) < SCAN_LEVEL:   # 평온하면 주의·하락 가정으로 강제 스캔
            trig.update({"level": SCAN_LEVEL, "level_name": LEVEL_NAME[SCAN_LEVEL],
                         "level_desc": LEVEL_DESC[SCAN_LEVEL], "direction": "down",
                         "window": "manual", "window_move": trig.get("change") or 0.0})
        return _do_scan(send_kakao, trig, now)
    return check_and_scan(send_kakao=send_kakao)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    print(run(send_kakao=False, force="--force" in sys.argv))
