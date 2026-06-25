"""
agent/holdings_watchdog.py
===========================
보유종목 중대공시 감시 에이전트.

내 보유종목 + 관심종목의 DART 공시 중:
  - 치명적 키워드(거래정지/관리종목/감사의견/횡령 등) → 룰 기반 즉시 카톡 (LLM 비경유)
  - 그 외 공시 → LLM이 중요도 판단, 중요 시에만 카톡 (면책 문구 자동)

스케줄: 평일 09:05~16:35 매 30분
수동:   python -m agent.holdings_watchdog
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5001")

# 룰 기반 즉시 경보 — 오탐이 있어도 미탐보다 낫다
CRITICAL_KEYWORDS = (
    "거래정지", "매매거래정지", "관리종목", "상장폐지", "상장적격성",
    "불성실공시", "감사의견", "의견거절", "한정", "부적정",
    "횡령", "배임", "회생절차", "파산", "자본잠식",
    "무상감자", "감자결정",
)
# LLM 판단 없이도 알릴 가치가 있는 주요 이벤트 (정보성)
NOTABLE_KEYWORDS = (
    "유상증자", "전환사채", "신주인수권", "자기주식", "주식분할",
    "합병", "분할", "영업양수", "영업양도", "최대주주변경", "단일판매",
)

_MAX_LLM_PER_RUN = 5


def _ensure_table():
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_watchdog_alerts (
                    rcept_no   VARCHAR(30) PRIMARY KEY,
                    code       CHAR(6),
                    corp_name  VARCHAR(100),
                    report_nm  VARCHAR(255),
                    level      ENUM('critical','notable','llm') NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_created (created_at DESC)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()


def _get_watch_codes() -> dict:
    """보유종목 + 관심종목 → {code: name}"""
    from database.db_connection import get_db_connection
    codes: dict = {}
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, name FROM stock_holdings WHERE quantity > 0")
            for r in cur.fetchall():
                codes[r['code'].zfill(6)] = r['name']
            try:
                cur.execute("SELECT stock_code AS code, stock_name AS name FROM watchlist_items")
                for r in cur.fetchall():
                    codes.setdefault(r['code'].zfill(6), r['name'])
            except Exception:
                pass
    finally:
        conn.close()
    return codes


def _already_alerted(rcept_nos: list[str]) -> set:
    if not rcept_nos:
        return set()
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            ph = ','.join(['%s'] * len(rcept_nos))
            cur.execute(f"SELECT rcept_no FROM agent_watchdog_alerts WHERE rcept_no IN ({ph})",
                        rcept_nos)
            return {r['rcept_no'] for r in cur.fetchall()}
    finally:
        conn.close()


def _mark_alerted(items: list[dict]) -> None:
    if not items:
        return
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for it in items:
                cur.execute(
                    "INSERT IGNORE INTO agent_watchdog_alerts (rcept_no, code, corp_name, report_nm, level) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (it['rcept_no'], it['code'], it['corp_name'], it['report_nm'], it['level']))
        conn.commit()
    finally:
        conn.close()


def _fetch_filings(code: str, corp_code: str, dart_key: str) -> list[dict]:
    """해당 종목의 최근 2일 공시 목록."""
    end   = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    url = ('https://opendart.fss.or.kr/api/list.json'
           f'?crtfc_key={dart_key}&corp_code={corp_code}'
           f'&bgn_de={start}&end_de={end}&page_count=50')
    try:
        data = requests.get(url, timeout=8).json()
        if data.get('status') not in ('000', '013'):   # 013 = 데이터 없음
            logger.warning(f"[watchdog] {code} DART 오류: {data.get('message')}")
        return data.get('list') or []
    except Exception as e:
        logger.warning(f"[watchdog] {code} DART 조회 실패: {e}")
        return []


def _classify(report_nm: str) -> str | None:
    """critical / notable / None(LLM 판단행)"""
    for kw in CRITICAL_KEYWORDS:
        if kw in report_nm:
            return 'critical'
    for kw in NOTABLE_KEYWORDS:
        if kw in report_nm:
            return 'notable'
    return None


def run(send_kakao: bool = True) -> dict:
    now = datetime.now()
    if now.weekday() >= 5:
        return {"ok": True, "skipped": True, "reason": "주말"}

    dart_key = os.getenv('DART_API_KEY', '')
    if not dart_key:
        logger.warning("[watchdog] DART_API_KEY 없음 — 스킵")
        return {"ok": False, "error": "DART_API_KEY 없음"}

    _ensure_table()
    codes = _get_watch_codes()
    if not codes:
        return {"ok": True, "skipped": True, "reason": "보유/관심종목 없음"}

    try:
        from XGBoost_v2.dart_client import _load_corp_map
        corp_map = _load_corp_map()
    except Exception as e:
        logger.error(f"[watchdog] corp_map 로드 실패: {e}")
        return {"ok": False, "error": "corp_map 로드 실패"}

    # 공시 수집
    found: list[dict] = []
    for code, name in codes.items():
        corp_code = corp_map.get(code)
        if not corp_code:
            continue
        for f in _fetch_filings(code, corp_code, dart_key):
            found.append({
                'rcept_no':  f.get('rcept_no', ''),
                'code':      code,
                'corp_name': f.get('corp_name', name),
                'report_nm': f.get('report_nm', ''),
            })

    if not found:
        logger.info(f"[watchdog] 신규 공시 없음 (감시 {len(codes)}종목)")
        return {"ok": True, "watched": len(codes), "filings": 0, "alerts": 0}

    seen = _already_alerted([f['rcept_no'] for f in found])
    fresh = [f for f in found if f['rcept_no'] and f['rcept_no'] not in seen]

    critical, notable, candidates = [], [], []
    for f in fresh:
        level = _classify(f['report_nm'])
        if level == 'critical':
            f['level'] = 'critical'; critical.append(f)
        elif level == 'notable':
            f['level'] = 'notable'; notable.append(f)
        else:
            candidates.append(f)

    # LLM 중요도 판단 (호출 상한)
    llm_picked = []
    if candidates:
        try:
            from agent.llm_client import generate
            for f in candidates[:_MAX_LLM_PER_RUN]:
                ans = generate(
                    f"공시 제목: [{f['corp_name']}] {f['report_nm']}\n\n"
                    "이 공시가 주가에 즉각적·실질적 영향을 줄 가능성이 높은 경우에만 '중요'라고 답하세요.\n"
                    "정기보고서, 지분변동 신고, 임원 변경, IR/설명회, 단순 정정 공시는 '일반'입니다.\n"
                    "확신이 없으면 '일반'. 답은 '중요' 또는 '일반' 한 단어만.",
                    temperature=0.0, max_tokens=10)
                if ans and ans.strip().startswith('중요'):
                    f['level'] = 'llm'
                    llm_picked.append(f)
        except Exception as e:
            logger.warning(f"[watchdog] LLM 판단 스킵: {e}")

    alerts = critical + notable + llm_picked
    # LLM이 '일반'으로 거른 것도 기록해 중복 LLM 호출 방지
    skipped_llm = [dict(f, level='llm') for f in candidates[:_MAX_LLM_PER_RUN] if f not in llm_picked]
    _mark_alerted(alerts + skipped_llm)

    if alerts and send_kakao:
        from notify.send import send_message_to_self
        if critical:
            msg = "🚨 보유종목 중대공시\n" + "\n".join(
                f"· {f['corp_name']}({f['code']}): {f['report_nm'][:60]}" for f in critical[:8])
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/dart_alert")
        rest = notable + llm_picked
        if rest:
            msg = "📋 보유종목 주요공시\n" + "\n".join(
                f"· {f['corp_name']}({f['code']}): {f['report_nm'][:60]}" for f in rest[:8])
            send_message_to_self(msg, link_url=f"{APP_BASE_URL}/dart_alert",
                                 ai_generated=bool(llm_picked))

    summary = f"감시 {len(codes)}종목 | 신규공시 {len(fresh)} | 경보 {len(alerts)} (치명 {len(critical)})"
    logger.info(f"[watchdog] {summary}")
    return {"ok": True, "watched": len(codes), "filings": len(fresh),
            "alerts": len(alerts), "critical": len(critical)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
