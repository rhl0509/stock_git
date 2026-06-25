# -*- coding: utf-8 -*-
"""
섹터(KRX 업종) 데이터 — 네이버 금융 스크래핑 (무인증)
pykrx 는 KRX 계정 인증이 필요하여 사용하지 않음
"""
import logging
from fastapi import APIRouter, Request, Depends, Body
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
import requests as _req
import json
import os
import time as _time

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'cache', 'sector')
_HEADERS   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _load_cache(key: str, ttl_hours: float = 6):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    if _time.time() - os.path.getmtime(path) > ttl_hours * 3600:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(key: str, data) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(os.path.join(_CACHE_DIR, f"{key}.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def _fetch_sector_list() -> list:
    """네이버 금융 업종 목록 + 등락률 스크래핑"""
    url = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
    r   = _req.get(url, headers=_HEADERS, timeout=10)
    r.encoding = "euc-kr"
    soup = BeautifulSoup(r.text, "lxml")

    sectors = []
    for row in soup.select("table.type_1 tr"):
        a   = row.select_one("td a")
        tds = row.select("td")
        if not a or len(tds) < 2:
            continue
        try:
            rate = float(tds[1].text.strip().replace(",", "").replace("%", "") or 0)
        except Exception:
            rate = 0.0
        no = a["href"].split("no=")[-1]
        sectors.append({"code": no, "name": a.text.strip(), "rate": rate})

    sectors.sort(key=lambda x: x["rate"], reverse=True)
    return sectors


def _fetch_sector_stocks(no: str) -> list:
    """특정 업종 구성종목 스크래핑 → [{code, name, price, rate}, ...]
    네이버 업종 상세 테이블에 종목명·현재가·등락률이 함께 있어 키움 없이 조회 가능."""
    url  = f"https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={no}"
    r    = _req.get(url, headers=_HEADERS, timeout=10)
    r.encoding = "euc-kr"
    soup = BeautifulSoup(r.text, "lxml")

    stocks = []
    for row in soup.select("table.type_5 tr"):
        a = row.select_one("a[href*='item/main']")
        if not a or "code=" not in a.get("href", ""):
            continue
        tds  = row.select("td")
        if len(tds) < 4:
            continue
        code = a["href"].split("code=")[-1][:6]
        name = a.get_text(strip=True).rstrip("*")
        try:
            price = int(tds[1].get_text(strip=True).replace(",", "") or 0)
        except Exception:
            price = 0
        try:
            rate = float(tds[3].get_text(strip=True).replace(",", "").replace("%", "") or 0)
        except Exception:
            rate = 0.0
        stocks.append({"code": code, "name": name, "price": price, "rate": rate})
    return stocks


# ══════════════════════════════════════════════════════
# ── 섹터 목록 ──
# ══════════════════════════════════════════════════════

@router.get('/sector/list')
def sector_list():
    """
    네이버 금융 업종 목록 + 등락률 반환.
    6시간 파일 캐시.
    """
    from datetime import datetime
    cache_key = f"list_naver_{datetime.now().strftime('%Y%m%d_%H')}"
    cached    = _load_cache(cache_key, ttl_hours=6)
    if cached:
        return cached

    try:
        sectors = _fetch_sector_list()
        result  = {"count": len(sectors), "sectors": sectors}
        _save_cache(cache_key, result)
        return result
    except Exception as e:
        logger.error(f'[sector] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)


# ══════════════════════════════════════════════════════
# ── 섹터 구성종목 ──
# ══════════════════════════════════════════════════════

@router.post('/sector/stocks')
def sector_stocks(request: Request, body: dict = Body(default={})):
    """
    업종 구성종목 코드 목록 반환.
    가격 조회는 프론트에서 /kiwoom/related-stocks/prices 로 수행.

    요청 body: {"code": "307", "name": "가전제품"}
    """
    sector_code = body.get('code', '').strip()
    sector_name = body.get('name', sector_code)

    if not sector_code:
        return JSONResponse({"error": "code 필요"}, status_code=400)

    from datetime import datetime
    cache_key = f"stocks_v2_{sector_code}_{datetime.now().strftime('%Y%m%d')}"
    cached    = _load_cache(cache_key, ttl_hours=12)
    if cached:
        return cached

    try:
        stocks = _fetch_sector_stocks(sector_code)
        stocks.sort(key=lambda s: s["rate"], reverse=True)
        result = {
            "sector_code": sector_code,
            "sector_name": sector_name,
            "total_count": len(stocks),
            "codes":       [s["code"] for s in stocks],   # 기존 호환
            "stocks":      stocks,                          # 종목명·현재가·등락률 포함
        }
        _save_cache(cache_key, result)
        return result
    except Exception as e:
        logger.error(f'[sector] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
