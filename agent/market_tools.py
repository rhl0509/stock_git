"""
agent/market_tools.py
=====================
마켓 코파일럿(시장전반 대화형 에이전트)의 Claude tool-use 도구 레지스트리.

설계 원칙 (사용자 요구 4번 "없는 정보로 거짓말 금지"):
  - 모든 도구는 기존 데이터 래퍼를 호출만 한다 (신규 수집 없음).
  - 결과는 반드시 {"source", "as_of", "data" | "error"} 로 감싼다.
    → Claude가 답변에 출처·시각을 인용할 수 있고, 실패는 정직하게 드러난다.
  - 데이터가 비어있거나(=수집 실패 sentinel) 오래됐으면 "stale"/"empty" 플래그를 단다.

TOOLS         : Claude messages API에 넘길 tool 스키마 리스트
dispatch(...) : tool_use 한 건을 실행해 tool_result content(JSON 문자열) 반환
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 결과 래핑 헬퍼
# ─────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _ok(source: str, data, as_of: str | None = None,
        note: str | None = None, stale: str | None = None) -> dict:
    out = {"source": source, "as_of": as_of or _now(), "data": data}
    if note:
        out["note"] = note
    if stale:
        out["stale"] = stale   # 신선도 경고 라벨 (예: "17분 지연", "2일 정체")
    return out


def _err(source: str, message: str) -> dict:
    return {"source": source, "as_of": _now(), "error": message}


def _all_zero(d: dict) -> bool:
    """수집 실패 시 래퍼들이 0.0 으로 채워 반환하는 sentinel 감지."""
    vals = [v for v in d.values() if isinstance(v, (int, float))]
    return bool(vals) and all(v == 0 for v in vals)


# ─────────────────────────────────────────────────────────────────
# 네이버 실시간 시세 + 신선도 (8단계)
# ─────────────────────────────────────────────────────────────────
_NAVER_H = {"User-Agent": "Mozilla/5.0"}

def _age_min(iso: str):
    """ISO 타임스탬프(예: 2026-06-23T14:25:19+09:00)의 경과 분. 실패 시 None."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso)
        now = datetime.now(dt.tzinfo)
        return max(0.0, (now - dt).total_seconds() / 60)
    except Exception:
        return None


def _stale_label(as_of_iso: str, status: str | None) -> str | None:
    """신선도 경고 라벨. 장중 15분+ 지연 또는 1일+ 정체일 때만."""
    age = _age_min(as_of_iso)
    if age is None:
        return None
    if status == "OPEN" and age > 15:
        return f"{int(age)}분 지연"
    if age > 24 * 60:
        return f"{int(age / 60 / 24)}일 정체"
    return None


def _naver_quote(code: str):
    """네이버 실시간 종목 시세 {price, change, as_of, status}. 실패 시 None."""
    import requests
    try:
        r = requests.get(f"https://m.stock.naver.com/api/stock/{code}/basic",
                          headers=_NAVER_H, timeout=6).json()
        price = float(str(r.get("closePrice", "0")).replace(",", ""))
        if not price:
            return None
        try:
            chg = float(str(r.get("fluctuationsRatio", "")).replace(",", ""))
        except Exception:
            chg = None
        return {"price": price, "change": chg,
                "as_of": r.get("localTradedAt", ""), "status": r.get("marketStatus", "")}
    except Exception:
        return None


def _naver_index(name: str):
    """네이버 실시간 지수 시세(KOSPI/KOSDAQ). 실패 시 None."""
    import requests
    try:
        r = requests.get(f"https://m.stock.naver.com/api/index/{name}/basic",
                          headers=_NAVER_H, timeout=6).json()
        price = float(str(r.get("closePrice", "0")).replace(",", ""))
        if not price:
            return None
        try:
            chg = float(str(r.get("fluctuationsRatio", "")).replace(",", ""))
        except Exception:
            chg = None
        return {"price": price, "change": chg,
                "as_of": r.get("localTradedAt", ""), "status": r.get("marketStatus", "")}
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# 개별 도구 구현
# ─────────────────────────────────────────────────────────────────
def _get_macro_kr() -> dict:
    from XGBoost_v2.bok_client import get_macro_features
    try:
        d = get_macro_features()
    except Exception as e:
        return _err("한국은행 ECOS", f"거시지표 조회 실패: {e}")
    if not d or _all_zero(d):
        return _err("한국은행 ECOS", "거시지표를 가져오지 못했습니다(빈 응답). 추정하지 마세요.")
    return _ok("한국은행 ECOS", d, note="ECOS 통계는 보통 1영업일 지연 공표됩니다.")


def _get_global_markets() -> dict:
    from XGBoost_v2.global_features import get_global_features
    try:
        d = get_global_features()
    except Exception as e:
        return _err("yfinance(글로벌지수)", f"글로벌 지수 조회 실패: {e}")
    if not d or _all_zero(d):
        return _err("yfinance(글로벌지수)", "글로벌 지수를 가져오지 못했습니다(빈 응답). 추정하지 마세요.")
    return _ok("yfinance(글로벌지수)", d)


def _get_kr_sectors() -> dict:
    from XGBoost_v2.global_features import get_kr_sector_snapshot
    try:
        d = get_kr_sector_snapshot()
    except Exception as e:
        return _err("네이버금융(KOSPI 업종)", f"국내 업종 조회 실패: {e}")
    sectors = (d or {}).get("sectors") or []
    if not sectors:
        return _err("네이버금융(KOSPI 업종)", "업종 등락 데이터를 가져오지 못했습니다.")
    return _ok("네이버금융(KOSPI 업종)", d, as_of=d.get("updated_at") or None)


def _get_us_sectors() -> dict:
    from XGBoost_v2.global_features import get_us_sector_snapshot
    try:
        d = get_us_sector_snapshot()
    except Exception as e:
        return _err("yfinance(美 섹터ETF)", f"미국 섹터 조회 실패: {e}")
    sectors = (d or {}).get("sectors") or []
    if not sectors:
        return _err("yfinance(美 섹터ETF)", "미국 섹터 데이터를 가져오지 못했습니다.")
    return _ok("yfinance(美 섹터ETF)", d, as_of=d.get("updated_at") or None)


def _get_market_news(keyword: str = "코스피 증시") -> dict:
    from XGBoost_v2.naver_news import search_news
    kw = (keyword or "코스피 증시").strip()
    try:
        items = search_news(kw, display=10) or []
    except Exception as e:
        return _err("네이버뉴스", f"뉴스 검색 실패: {e}")
    if not items:
        return _err("네이버뉴스", f"'{kw}' 관련 뉴스를 찾지 못했습니다.")
    # 제목/일자만 추려 토큰 절약 (HTML 태그 제거)
    import re
    tag = re.compile(r"<[^>]+>")
    titles = [
        {"title": tag.sub("", it.get("title", "")).strip(),
         "date":  it.get("pubDate", "")}
        for it in items[:10]
    ]
    return _ok("네이버뉴스", {"keyword": kw, "articles": titles})


# ─────────────────────────────────────────────────────────────────
# 2단계: 단일종목 + 포트폴리오
# ─────────────────────────────────────────────────────────────────
def _search_stock(query: str) -> dict:
    """종목명/코드 → 후보 리스트(코드 확정용). kr_stocks 테이블 검색."""
    q = (query or "").strip()
    if not q:
        return _err("kr_stocks DB", "검색어가 비었습니다.")
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT code, name, market FROM kr_stocks
                WHERE name LIKE %s OR code LIKE %s
                ORDER BY CASE WHEN name=%s OR code=%s THEN 0
                              WHEN name LIKE %s THEN 1 ELSE 2 END, LENGTH(name)
                LIMIT 8
            """, (f'%{q}%', f'{q}%', q, q, f'{q}%'))
            rows = cur.fetchall() or []
    except Exception as e:
        return _err("kr_stocks DB", f"종목 검색 실패: {e}")
    finally:
        conn.close()
    if not rows:
        return _err("kr_stocks DB", f"'{q}'에 해당하는 종목을 찾지 못했습니다.")
    return _ok("kr_stocks DB", {"query": q, "candidates": rows})


def _get_stock_analysis(code: str) -> dict:
    """단일종목 통합 스냅샷 — 과금 제거판에서는 비활성화(LLM 어드바이저 의존)."""
    c = (code or "").strip().zfill(6)
    if not c.isdigit():
        return _err("통합분석", "유효한 6자리 종목코드가 필요합니다. 먼저 search_stock으로 코드를 확정하세요.")
    return _err("통합분석", "통합분석 기능은 이 버전에서 비활성화되어 있습니다.")

    kw, yf = r.get("kw") or {}, r.get("yf") or {}
    if not kw and not yf:
        return _err("통합분석", "현재가·시세를 가져오지 못했습니다(키움 미연결 등). 추정하지 마세요.")

    # 뉴스는 제목만 추려 토큰 절약
    import re
    tag = re.compile(r"<[^>]+>")
    raw_news = yf.get("news") or r.get("news") or []
    news = []
    if isinstance(raw_news, list):
        for n in raw_news[:6]:
            if isinstance(n, dict):
                news.append({"title": tag.sub("", (n.get("title") or "")).strip(),
                             "date": n.get("pubDate") or n.get("date", "")})
            elif isinstance(n, str):
                news.append({"title": tag.sub("", n).strip()})

    tech = {k: v for k, v in yf.items() if k != "news"}
    data = {
        "code":           c,
        "quote_kiwoom":   kw,            # 현재가/거래량/시총/PER/PBR/ROE/52주 등
        "technicals":     tech,          # 이평·RSI·MACD·볼린저·ATR손절·피보·52주위치
        "financials_dart": r.get("dart") or {},
        "flows_kis":      r.get("kis") or {},     # 기관/외인 수급
        "consensus":      r.get("consensus") or {},  # 목표주가/의견
        "ml":             r.get("ml") or {},      # 상승확률/신호
        "short":          r.get("short") or {},   # 공매도
        "news":           news,
    }

    # 현재가 소스: 키움(실시간) > 네이버(실시간) > yfinance(지연)
    stale = None
    if kw.get("price"):
        data["price_source"], data["price_as_of"] = "키움 실시간", None
    else:
        nv = _naver_quote(c)
        if nv:
            tech["current_price"] = nv["price"]       # 카드/분석이 이 값을 사용
            data["price_source"], data["price_as_of"] = "네이버 실시간", nv["as_of"]
            stale = _stale_label(nv["as_of"], nv["status"])
        else:
            data["price_source"], data["price_as_of"] = "yfinance(지연 가능)", None
            stale = "지연 가능(yfinance 종가)"
    note = None if data["price_source"].startswith(("키움", "네이버")) else \
        "키움·네이버 실시간 미연결 — yfinance 종가 기준일 수 있음."
    return _ok("키움·네이버·yfinance·DART·KIS·ML 통합", data, note=note, stale=stale)


def _get_index_quote() -> dict:
    """국내외 주요 지수·원자재·환율 실시간 수준과 등락률.
    KR 지수(KOSPI/KOSDAQ)는 네이버 실시간으로 갱신해 지연을 줄인다."""
    from routes.stock_api import _fetch_indices_sync
    try:
        data = _fetch_indices_sync()
    except Exception as e:
        return _err("yfinance 지수", f"지수 조회 실패: {e}")
    if not data:
        return _err("yfinance 지수", "지수 데이터를 가져오지 못했습니다.")

    stale, kr_as_of, used_naver = None, None, False
    for it in data:
        if it.get("name") in ("KOSPI", "KOSDAQ"):
            nv = _naver_index(it["name"])
            if nv:
                it["price"], it["change"] = nv["price"], nv["change"]
                it["as_of"], it["source"] = nv["as_of"], "네이버 실시간"
                used_naver = True
                if it["name"] == "KOSPI":
                    kr_as_of = nv["as_of"]
                    stale = _stale_label(nv["as_of"], nv["status"])
    src = "네이버 실시간(KR지수)+yfinance(해외·원자재·환율)" if used_naver else "yfinance(지수·원자재·환율)"
    return _ok(src, {"items": data}, as_of=kr_as_of, stale=stale)


def _get_my_portfolio(user_no) -> dict:
    """보유종목 + 평가손익 자동집계. DB(stock_holdings, 평균단가) + 키움 현재가."""
    if not user_no:
        return _err("보유종목", "로그인 정보가 없어 보유종목을 조회할 수 없습니다.")
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, name, quantity, avg_price FROM stock_holdings "
                "WHERE member_id=%s AND quantity > 0", (int(user_no),))
            rows = cur.fetchall() or []
    except Exception as e:
        return _err("보유종목", f"보유종목 조회 실패: {e}")
    finally:
        conn.close()

    if not rows:
        # DB 미동기화면 키움 실시간 목록만(손익 없이) 폴백
        try:
            from routes.dividend import _get_holdings_for
            hs, src = _get_holdings_for(int(user_no))
        except Exception:
            hs = []
        if not hs:
            return _err("보유종목",
                        "보유종목이 없습니다(또는 키움 미연결·DB 미동기화). 포트폴리오에서 키움 동기화를 먼저 하세요.")
        return _ok("보유종목(키움, 평균단가 없음)",
                   {"holdings": hs, "note": "평균단가 미동기화로 손익 계산 불가."})

    try:
        from kiwoom_client import kiwoom
    except Exception:
        kiwoom = None

    holdings, total_invest, total_asset, priced = [], 0.0, 0.0, 0
    for h in rows:
        avg = float(h.get("avg_price") or 0)
        qty = int(h.get("quantity") or 0)
        cur_price, src = avg, "평균단가(폴백)"
        got = False
        if kiwoom is not None:
            try:
                pd = kiwoom.get_best_price(h["code"])
                if pd and pd.get("price"):
                    cur_price = float(pd["price"]); src = pd.get("price_source", "키움")
                    priced += 1; got = True
            except Exception:
                pass
        if not got:   # 키움 미연결 → 네이버 실시간으로 현재가 보강
            nv = _naver_quote(h["code"])
            if nv:
                cur_price = nv["price"]; src = "네이버 실시간"; priced += 1
        invest, ev = avg * qty, cur_price * qty
        profit = ev - invest
        holdings.append({
            "code": h["code"], "name": h["name"], "quantity": qty,
            "avg_price": round(avg), "current_price": round(cur_price),
            "profit": round(profit),
            "profit_rate": round(profit / invest * 100, 2) if invest else 0,
            "price_source": src,
        })
        total_invest += invest; total_asset += ev

    total_profit = total_asset - total_invest
    summary = {
        "total_invest": round(total_invest), "total_asset": round(total_asset),
        "total_profit": round(total_profit),
        "total_profit_rate": round(total_profit / total_invest * 100, 2) if total_invest else 0,
    }
    note = ("실시간 시세 미연결 — 평가액은 평균단가 기준(손익 0)입니다."
            if priced == 0 else None)
    return _ok("보유종목 DB + 실시간 시세(키움/네이버)",
               {"holdings": holdings, "summary": summary}, note=note)


# ─────────────────────────────────────────────────────────────────
# 도구 스키마 + 디스패치
# ─────────────────────────────────────────────────────────────────
_NOARG = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS = [
    {
        "name": "get_macro_kr",
        "description": "한국 거시지표 조회: KOSPI 20일 수익률/추세, 원달러 환율 20일 변화, "
                       "국고채 3년 금리, 콜금리. '금리 어때', '환율', '거시 환경' 등에 사용.",
        "input_schema": _NOARG,
    },
    {
        "name": "get_global_markets",
        "description": "해외 지수 조회: S&P500(1·5일), 나스닥(1일), VIX 변동성, 유가(20일), "
                       "미국 10년물 국채금리. '미국 증시', '밤사이 글로벌', 'VIX' 등에 사용.",
        "input_schema": _NOARG,
    },
    {
        "name": "get_kr_sectors",
        "description": "국내 KOSPI 업종별 당일 등락률과 종목 수(네이버금융). "
                       "'오늘 어떤 섹터', '국내 업종 흐름', '강세 업종' 등에 사용.",
        "input_schema": _NOARG,
    },
    {
        "name": "get_us_sectors",
        "description": "미국 11개 섹터 ETF의 1·5일 수익률과 S&P/나스닥/VIX 현황. "
                       "'미국 섹터', '어떤 산업이 강한지(미국)' 등에 사용.",
        "input_schema": _NOARG,
    },
    {
        "name": "get_market_news",
        "description": "시장/증시 관련 최신 뉴스 제목을 네이버뉴스에서 검색. "
                       "기본 키워드는 '코스피 증시'. 특정 테마가 궁금하면 keyword 지정.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "검색 키워드(예: '반도체', '금리 인하'). 미지정 시 '코스피 증시'."}
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_index_quote",
        "description": "주요 지수·원자재·환율의 실시간 수준과 등락률: KOSPI·KOSDAQ·나스닥·S&P500, "
                       "금·은·WTI유, 달러·유로·엔화 환율. '코스피 지금 몇 포인트', '지수 현재가', "
                       "'환율/금값' 등에 사용. (등락률이 null이면 전일 종가 결측 — 0%로 단정 금지)",
        "input_schema": _NOARG,
    },
    {
        "name": "search_stock",
        "description": "종목명(또는 코드 일부)으로 종목을 검색해 정확한 6자리 코드를 찾는다. "
                       "사용자가 종목을 언급하면(예: '삼성전자', '하이닉스') 먼저 이 도구로 코드를 확정한 뒤 "
                       "get_stock_analysis를 호출하라. 후보가 여러 개면 사용자에게 확인.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "종목명 또는 코드(예: '삼성전자', '005930')"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_stock_analysis",
        "description": "단일종목 통합 분석: 현재가·시총·PER/PBR/ROE(키움), 이평·RSI·MACD·ATR손절·52주위치(기술), "
                       "매출·영업이익·부채비율(DART), 기관/외인 수급(KIS), 애널리스트 목표주가·의견, ML 상승확률, "
                       "공매도, 관련 뉴스. 반드시 6자리 코드 필요(search_stock으로 먼저 확정).",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "6자리 종목코드(예: '005930')"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_my_portfolio",
        "description": "로그인한 사용자의 현재 보유종목 목록(종목·수량). '내 종목', '내 포트폴리오', "
                       "'내가 가진 거 어때' 같은 질문에 사용. 개별 종목 상세는 get_stock_analysis로 이어서 조회.",
        "input_schema": _NOARG,
    },
    {
        "name": "ask_user",
        "description": "답하기에 정보가 부족하거나 질문이 모호할 때, 추측하지 말고 사용자에게 "
                       "되물을 때 사용. 어떤 기간·시장·종목인지 등을 명확히 한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "사용자에게 할 구체적 질문."}
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
]

_HANDLERS = {
    "get_macro_kr":       lambda inp, ctx: _get_macro_kr(),
    "get_global_markets": lambda inp, ctx: _get_global_markets(),
    "get_kr_sectors":     lambda inp, ctx: _get_kr_sectors(),
    "get_us_sectors":     lambda inp, ctx: _get_us_sectors(),
    "get_market_news":    lambda inp, ctx: _get_market_news(inp.get("keyword", "코스피 증시")),
    "get_index_quote":    lambda inp, ctx: _get_index_quote(),
    "search_stock":       lambda inp, ctx: _search_stock(inp.get("query", "")),
    "get_stock_analysis": lambda inp, ctx: _get_stock_analysis(inp.get("code", "")),
    "get_my_portfolio":   lambda inp, ctx: _get_my_portfolio((ctx or {}).get("user_no")),
    # ask_user 는 루프에서 특별 처리(실행하지 않고 사용자에게 전달)되므로 여기 없음
}


def dispatch(name: str, tool_input: dict, context: dict | None = None) -> tuple[str, bool]:
    """tool_use 한 건 실행 → (tool_result content 문자열, is_error). context: {user_no} 등."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps(_err(name, f"알 수 없는 도구: {name}"), ensure_ascii=False), True
    try:
        result = handler(tool_input or {}, context or {})
    except Exception as e:
        logger.error(f"[market_tools] {name} 실행 오류: {e}", exc_info=True)
        return json.dumps(_err(name, f"도구 실행 오류: {e}"), ensure_ascii=False), True
    is_error = "error" in result
    return json.dumps(result, ensure_ascii=False), is_error
