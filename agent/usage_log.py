"""
agent/usage_log.py
==================
Claude(Anthropic) API 호출의 실제 토큰·비용을 DB에 기록·집계.

마켓 코파일럿의 모든 모델 호출(웹 채팅·텔레그램·능동 브리핑·장중 알림)이
log_usage(model, response.usage, source) 로 1건씩 적재한다.

가격(USD/1M 토큰, 2026 기준):
  opus-4-8  $5/$25, haiku-4-5 $1/$5, sonnet-4-6 $3/$15
프롬프트 캐시: 쓰기 ~1.25x, 읽기 ~0.1x (input 단가 기준).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# (input, output) USD per 1M tokens
PRICING = {
    "claude-opus-4-8":  (5.0, 25.0),
    "claude-opus-4-7":  (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
USDKRW_FALLBACK = 1400  # 환율 조회 실패 시 폴백

_ready = False


def _get_usdkrw() -> float:
    """원화 환산용 환율 — 네비바(IndexBar)와 동일 소스(/market-indices '달러')를 참조."""
    try:
        from routes.stock_api import _INDICES_CACHE, _fetch_indices_sync
        data = _INDICES_CACHE.get("data") or _fetch_indices_sync()
        for it in (data or []):
            if it.get("name") == "달러" and it.get("price"):
                return round(float(it["price"]), 2)
    except Exception:
        pass
    return USDKRW_FALLBACK


def _ensure_table():
    global _ready
    if _ready:
        return
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage_log (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    model         VARCHAR(40),
                    source        VARCHAR(24),
                    input_tokens  INT DEFAULT 0,
                    output_tokens INT DEFAULT 0,
                    cache_read    INT DEFAULT 0,
                    cache_write   INT DEFAULT 0,
                    cost_usd      DECIMAL(12,6) DEFAULT 0,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_created (created_at)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
        _ready = True
    finally:
        conn.close()


def _cost(model: str, in_tok: int, out_tok: int, c_read: int, c_write: int) -> float:
    rate = PRICING.get(model)
    if not rate:
        return 0.0
    rin, rout = rate
    return (in_tok * rin + c_write * rin * 1.25 + c_read * rin * 0.1
            + out_tok * rout) / 1_000_000


def log_usage(model: str, usage, source: str) -> None:
    """모델 호출 1건의 토큰·비용 기록. 절대 메인 흐름을 깨지 않는다(try/except)."""
    try:
        _ensure_table()
        in_tok  = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        c_read  = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        c_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cost = round(_cost(model, in_tok, out_tok, c_read, c_write), 6)
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO llm_usage_log "
                    "(model, source, input_tokens, output_tokens, cache_read, cache_write, cost_usd) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (model, source, in_tok, out_tok, c_read, c_write, cost))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[usage_log] 기록 실패: {e}")


def _f(v):  # Decimal/None → float
    return round(float(v or 0), 4)


# 기간(period)별 집계 설정 — 그룹 표현식은 화이트리스트(사용자 입력을 SQL에 직접 넣지 않음).
# (그룹 SQL, 조회 윈도우 일수, 막대 개수)
_BUCKET = {
    "day":   ("DATE(created_at)",                                          30,        30),
    "week":  ("DATE_SUB(DATE(created_at), INTERVAL WEEKDAY(created_at) DAY)", 7 * 12,  12),
    "month": ("DATE_FORMAT(created_at, '%%Y-%%m-01')",                     366,       12),
    "year":  ("DATE_FORMAT(created_at, '%%Y-01-01')",                      366 * 5,   5),
}


def _bucket_label(period: str, key) -> str:
    """버킷 키(날짜/문자열)를 축에 표시할 짧은 라벨로 변환."""
    s = str(key)
    if period == "year":
        return s[:4]              # 2026
    if period == "month":
        return s[:7]              # 2026-06
    return s[5:10]               # MM-DD (일별/주별 시작일)


def get_summary(period: str = "day", days: int | None = None) -> dict:
    """비용 집계: 오늘/이번달/기간합계 + 기간별 시계열·소스별·모델별 + 최근 호출.

    period: day(일별·30일) / week(주별·12주) / month(월별·12개월) / year(연별·5년).
    days: 하위호환용 — 주어지면 무시되고 period로 동작(기존 호출 안전).
    """
    period = period if period in _BUCKET else "day"
    expr, window, _limit = _BUCKET[period]

    _ensure_table()
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM llm_usage_log "
                        "WHERE DATE(created_at)=CURDATE()")
            today = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM llm_usage_log "
                        "WHERE created_at>=DATE_FORMAT(CURDATE(),'%%Y-%%m-01')")
            month = cur.fetchone()
            cur.execute("SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM llm_usage_log "
                        "WHERE created_at>=CURDATE()-INTERVAL %s DAY", (window,))
            period_total = cur.fetchone()
            cur.execute(f"SELECT {expr} k, COALESCE(SUM(cost_usd),0) c, COUNT(*) n "
                        f"FROM llm_usage_log WHERE created_at>=CURDATE()-INTERVAL %s DAY "
                        f"GROUP BY k ORDER BY k", (window,))
            series = cur.fetchall()
            cur.execute("SELECT source, COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM llm_usage_log "
                        "WHERE created_at>=CURDATE()-INTERVAL %s DAY GROUP BY source ORDER BY c DESC", (window,))
            by_source = cur.fetchall()
            cur.execute("SELECT model, COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM llm_usage_log "
                        "WHERE created_at>=CURDATE()-INTERVAL %s DAY GROUP BY model ORDER BY c DESC", (window,))
            by_model = cur.fetchall()
            cur.execute("SELECT created_at, model, source, input_tokens, output_tokens, cost_usd "
                        "FROM llm_usage_log ORDER BY id DESC LIMIT 40")
            recent = cur.fetchall()
    finally:
        conn.close()

    rate = _get_usdkrw()   # 네비바 달러 환율 참조

    def _row(r):
        return {"cost_usd": _f(r["c"]), "cost_krw": round(_f(r["c"]) * rate), "count": int(r["n"])}

    return {
        "usdkrw": rate,
        "period": period,
        "today": _row(today),
        "month": _row(month),
        "period_total": _row(period_total),
        "series": [{"key": str(r["k"]), "label": _bucket_label(period, r["k"]), **_row(r)} for r in series],
        "by_source": [{"source": r["source"] or "기타", **_row(r)} for r in by_source],
        "by_model": [{"model": r["model"] or "?", **_row(r)} for r in by_model],
        "recent": [{
            "ts": r["created_at"].strftime("%m-%d %H:%M") if r["created_at"] else "",
            "model": r["model"], "source": r["source"],
            "in": int(r["input_tokens"] or 0), "out": int(r["output_tokens"] or 0),
            "cost_usd": _f(r["cost_usd"]), "cost_krw": round(_f(r["cost_usd"]) * rate),
        } for r in recent],
    }
