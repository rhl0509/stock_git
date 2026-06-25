"""
routes/morning_news.py — 개장 전 뉴스 크롤링 (매일 08:40 자동 실행)
키워드: KEYWORDS (고정)
소스: Google News RSS
DB: morning_news 테이블
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from routes.utils import api_require_login, require_login
from templates_config import render

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_KEYWORDS = ['스케줄', '개장 전']
_RSS = 'https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko'

# 60초 인메모리 캐시 — DB를 매번 조회하지 않도록
_kw_cache: list = []
_kw_cache_ts: float = 0.0

# 카카오 알림 설정 캐시
_kakao_notify: bool = True
_kakao_notify_loaded: bool = False


def _get_kakao_notify() -> bool:
    global _kakao_notify, _kakao_notify_loaded
    if _kakao_notify_loaded:
        return _kakao_notify
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT val FROM morning_news_settings WHERE key_name = 'kakao_notify'")
            row = cur.fetchone()
            _kakao_notify = (row['val'] == '1') if row else True
            _kakao_notify_loaded = True
    except Exception:
        _kakao_notify = True
    finally:
        conn.close()
    return _kakao_notify


def _set_kakao_notify(val: bool):
    global _kakao_notify, _kakao_notify_loaded
    _kakao_notify = val
    _kakao_notify_loaded = True
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO morning_news_settings (key_name, val) VALUES ('kakao_notify', %s) "
                "ON DUPLICATE KEY UPDATE val = %s",
                ('1' if val else '0', '1' if val else '0')
            )
        conn.commit()
    finally:
        conn.close()


def get_keywords() -> list[str]:
    import time
    global _kw_cache, _kw_cache_ts
    if time.time() - _kw_cache_ts < 60 and _kw_cache:
        return _kw_cache
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT keyword FROM morning_news_keywords ORDER BY id")
            _kw_cache = [r['keyword'] for r in cur.fetchall()]
            _kw_cache_ts = time.time()
    finally:
        conn.close()
    return _kw_cache


def _invalidate_kw_cache():
    global _kw_cache_ts
    _kw_cache_ts = 0.0


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morning_news (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    keyword    VARCHAR(50)  NOT NULL,
                    title      TEXT         NOT NULL,
                    link       TEXT         NOT NULL,
                    source     VARCHAR(200),
                    pub_date   DATETIME,
                    crawled_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_link (link(255))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morning_news_keywords (
                    id      INT AUTO_INCREMENT PRIMARY KEY,
                    keyword VARCHAR(50) NOT NULL UNIQUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS morning_news_settings (
                    key_name VARCHAR(50) PRIMARY KEY,
                    val      VARCHAR(200) NOT NULL DEFAULT ''
                )
            """)
            # 기본 키워드 시드 (테이블이 비어있을 때만)
            cur.execute("SELECT COUNT(*) AS cnt FROM morning_news_keywords")
            if cur.fetchone()['cnt'] == 0:
                for kw in _DEFAULT_KEYWORDS:
                    cur.execute(
                        "INSERT IGNORE INTO morning_news_keywords (keyword) VALUES (%s)", (kw,)
                    )
        conn.commit()
    finally:
        conn.close()


def crawl_and_save() -> int:
    """키워드별 Google News RSS 크롤링 후 DB 저장. 저장된 신규 건수 반환."""
    saved = 0
    for kw in get_keywords():
        url = _RSS.format(q=quote(kw))
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            r.raise_for_status()
        except Exception as e:
            logger.error(f'[morning_news] 크롤링 실패 kw={kw}: {e}')
            continue

        root = ET.fromstring(r.content)
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                for item in root.findall('./channel/item'):
                    title = item.findtext('title', '').strip()
                    link  = item.findtext('link',  '').strip()
                    if not title or not link:
                        continue

                    source_el = item.find('source')
                    source = source_el.text if source_el is not None else ''
                    if not source and ' - ' in title:
                        title, source = title.rsplit(' - ', 1)

                    pub_dt = None
                    pub_raw = item.findtext('pubDate', '')
                    if pub_raw:
                        try:
                            pub_dt = parsedate_to_datetime(pub_raw).replace(tzinfo=None)
                        except Exception:
                            pass

                    try:
                        cur.execute(
                            "INSERT IGNORE INTO morning_news "
                            "(keyword, title, link, source, pub_date) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (kw, title, link, source, pub_dt)
                        )
                        saved += cur.rowcount
                    except Exception:
                        pass
            conn.commit()
        finally:
            conn.close()

    logger.info(f'[morning_news] 크롤링 완료: {saved}건 저장')
    return saved


def _fetch_today_items() -> dict:
    """오늘 수집된 항목을 키워드별로 반환 {kw: [title, ...]}."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT keyword, title FROM morning_news "
                "WHERE crawled_at >= NOW() - INTERVAL 2 HOUR "
                "ORDER BY pub_date DESC, id DESC"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    result = {kw: [] for kw in get_keywords()}
    for row in rows:
        kw = row['keyword']
        if kw in result:
            result[kw].append(row['title'])
    return result


def _send_kakao_news():
    """오늘 수집 뉴스를 카카오톡으로 발송."""
    try:
        from notify.send import send_message_to_self
        import os
        items = _fetch_today_items()
        has_any = any(titles for titles in items.values())
        if not has_any:
            return
        now_str = datetime.now().strftime('%m/%d %H:%M')
        lines = [f'📰 개장전 뉴스 ({now_str})', '']
        for kw, titles in items.items():
            if titles:
                lines.append(f'[{kw}]')
                for t in titles[:3]:
                    lines.append(f'  · {t[:60]}{"…" if len(t) > 60 else ""}')
                lines.append('')
        port = int(os.getenv('FLASK_PORT', '5000'))
        send_message_to_self('\n'.join(lines).strip(), link_url=f'http://localhost:{port}/morning_news')
        logger.info('[morning_news] 카카오 알림 발송')
    except Exception as e:
        logger.error(f'[morning_news] 카카오 알림 실패: {e}')


def crawl_and_notify() -> int:
    """크롤링 후 DB 저장. 카카오 알림 설정 시 발송. 스케줄러에서 호출."""
    saved = crawl_and_save()
    if _get_kakao_notify():
        _send_kakao_news()
    return saved


# ── 라우트 ──────────────────────────────────────────────────────────────────

@router.get('/morning_news', dependencies=[Depends(require_login)])
def morning_news_page(request: Request):
    return render(request, 'stock/morning_news.html')


@router.get('/api/morning_news', dependencies=[Depends(api_require_login)])
def api_morning_news(request: Request):
    """수집된 뉴스 목록. ?days=7&keyword=스케줄"""
    days = int(request.query_params.get('days', '7'))
    kw   = request.query_params.get('keyword', '').strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if kw:
                cur.execute(
                    "SELECT * FROM morning_news "
                    "WHERE keyword = %s AND crawled_at >= NOW() - INTERVAL %s DAY "
                    "ORDER BY pub_date DESC, id DESC LIMIT 300",
                    (kw, days)
                )
            else:
                cur.execute(
                    "SELECT * FROM morning_news "
                    "WHERE crawled_at >= NOW() - INTERVAL %s DAY "
                    "ORDER BY pub_date DESC, id DESC LIMIT 300",
                    (days,)
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    for row in rows:
        for col in ('pub_date', 'crawled_at'):
            if row.get(col):
                row[col] = row[col].strftime('%Y-%m-%d %H:%M')

    return {'ok': True, 'items': rows, 'total': len(rows),
            'keywords': get_keywords()}


@router.get('/api/morning_news/keywords', dependencies=[Depends(api_require_login)])
def api_keywords_get():
    return {'ok': True, 'keywords': get_keywords()}


@router.post('/api/morning_news/keywords', dependencies=[Depends(api_require_login)])
def api_keywords_add(request: Request, body: dict = Body(default={})):
    kw = body.get('keyword', '').strip()
    if not kw:
        return JSONResponse({'ok': False, 'error': '키워드를 입력하세요'}, status_code=400)
    if len(kw) > 50:
        return JSONResponse({'ok': False, 'error': '키워드는 50자 이하'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT IGNORE INTO morning_news_keywords (keyword) VALUES (%s)", (kw,))
        conn.commit()
    finally:
        conn.close()
    _invalidate_kw_cache()
    return {'ok': True, 'keywords': get_keywords()}


@router.delete('/api/morning_news/keywords/{keyword}', dependencies=[Depends(api_require_login)])
def api_keywords_delete(keyword: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM morning_news_keywords WHERE keyword = %s", (keyword,))
        conn.commit()
    finally:
        conn.close()
    _invalidate_kw_cache()
    return {'ok': True, 'keywords': get_keywords()}


@router.post('/api/morning_news/run', dependencies=[Depends(api_require_login)])
def api_morning_news_run():
    """수동 즉시 크롤링. 카카오 알림 설정 시 발송."""
    try:
        saved = crawl_and_save()
        if _get_kakao_notify():
            _send_kakao_news()
        return {'ok': True, 'saved': saved,
                'run_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    except Exception as e:
        logger.error(f'[morning_news/run] {e}')
        logger.error(f'[morning_news] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/api/morning_news/kakao_setting', dependencies=[Depends(api_require_login)])
def api_kakao_setting_get():
    return {'ok': True, 'kakao_notify': _get_kakao_notify()}


@router.post('/api/morning_news/kakao_setting', dependencies=[Depends(api_require_login)])
def api_kakao_setting_set(request: Request, body: dict = Body(default={})):
    val = body.get('kakao_notify', True)
    _set_kakao_notify(bool(val))
    return {'ok': True, 'kakao_notify': bool(val)}


@router.get('/api/morning_news/stock', dependencies=[Depends(api_require_login)])
def api_morning_news_stock(request: Request):
    """종목 코드로 관련 뉴스 검색 (stock_detail 감성 섹션용). ?code=005930"""
    from XGBoost_v2.dart_client import _classify_report
    code = request.query_params.get('code', '').strip()
    if not code:
        return JSONResponse({'ok': False, 'error': 'code 필요'}, status_code=400)

    # 종목명 조회
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM kr_stocks WHERE code = %s LIMIT 1", (code,))
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return {'ok': True, 'items': []}

    name = row['name']
    # 검색어: 종목명에서 (주),(코스피) 등 제거 후 핵심 단어
    import re
    keyword = re.sub(r'[\(\)\[\]㈜주식회사]', '', name).strip()[:10]

    conn2 = get_db_connection()
    try:
        with conn2.cursor() as cur:
            cur.execute(
                "SELECT keyword, title, link, source, pub_date "
                "FROM morning_news "
                "WHERE title LIKE %s AND crawled_at >= NOW() - INTERVAL 7 DAY "
                "ORDER BY pub_date DESC LIMIT 20",
                (f'%{keyword}%',)
            )
            rows = cur.fetchall()
    finally:
        conn2.close()

    items = []
    for r in rows:
        category = _classify_report(r['title'])
        items.append({
            'keyword':  r['keyword'],
            'title':    r['title'],
            'link':     r['link'],
            'source':   r['source'] or '',
            'pub_date': r['pub_date'].strftime('%m/%d %H:%M') if r['pub_date'] else '',
            'category': category,
        })
    return {'ok': True, 'items': items, 'name': name}
