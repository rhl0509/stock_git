"""
routes/dart_alert.py — DART 공시 알림
관심 종목에 새 공시가 뜨면 카카오톡으로 알림.
스케줄: 평일 09:00~15:30, 30분마다
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from routes.utils import api_require_login, require_login
from templates_config import render

router = APIRouter()
logger = logging.getLogger(__name__)

CATEGORY_LABEL = {'positive': '📈 호재', 'negative': '📉 악재', 'neutral': '📋 일반'}


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dart_alert_watchlist (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    code       CHAR(6)      NOT NULL UNIQUE,
                    name       VARCHAR(100) NOT NULL,
                    added_at   DATETIME     DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dart_alert_history (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    code          CHAR(6)      NOT NULL,
                    disclose_date CHAR(8)      NOT NULL,
                    title         VARCHAR(500) NOT NULL,
                    category      VARCHAR(20),
                    sent_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_disc (code, disclose_date, title(200))
                )
            """)
        conn.commit()
    finally:
        conn.close()


def check_and_notify() -> int:
    """관심 종목 신규 공시 감지 → 카카오톡 알림. 발송 건수 반환."""
    try:
        from XGBoost_v2.dart_client import get_recent_disclosures
    except ImportError:
        logger.error('[dart_alert] dart_client import 실패')
        return 0

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, name FROM dart_alert_watchlist ORDER BY id")
            watchlist = cur.fetchall()
    finally:
        conn.close()

    if not watchlist:
        return 0

    new_items = []
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for stock in watchlist:
                code, name = stock['code'], stock['name']
                disclosures = get_recent_disclosures(code, days=3)
                for d in disclosures:
                    disc_date = d.get('date', '')
                    title     = d.get('title', '')
                    category  = d.get('category', 'neutral')
                    if not disc_date or not title:
                        continue
                    try:
                        cur.execute(
                            "INSERT IGNORE INTO dart_alert_history "
                            "(code, disclose_date, title, category) "
                            "VALUES (%s, %s, %s, %s)",
                            (code, disc_date, title, category)
                        )
                        if cur.rowcount:
                            new_items.append({'code': code, 'name': name,
                                              'date': disc_date, 'title': title,
                                              'category': category})
                    except Exception:
                        pass
        conn.commit()
    finally:
        conn.close()

    if not new_items:
        return 0

    try:
        from notify.send import send_message_to_self
        now_str = datetime.now().strftime('%m/%d %H:%M')
        lines = [f'📢 공시 알림 ({now_str})', '']
        for it in new_items[:10]:
            label = CATEGORY_LABEL.get(it['category'], '📋')
            date_fmt = f"{it['date'][:4]}-{it['date'][4:6]}-{it['date'][6:]}" if len(it['date']) == 8 else it['date']
            lines.append(f"{label}  {it['name']}({it['code']})")
            lines.append(f"  {date_fmt}  {it['title'][:60]}{'…' if len(it['title']) > 60 else ''}")
            lines.append('')
        if len(new_items) > 10:
            lines.append(f'외 {len(new_items) - 10}건 더')
        msg = '\n'.join(lines).strip()
        import os
        port = int(os.getenv('FLASK_PORT', '5000'))
        send_message_to_self(msg, link_url=f'http://localhost:{port}/dart_alert')
        logger.info(f'[dart_alert] 카카오 알림: {len(new_items)}건')
    except Exception as e:
        logger.error(f'[dart_alert] 카카오 알림 실패: {e}')

    return len(new_items)


# ── 페이지 ─────────────────────────────────────────────────────────────────

@router.get('/dart_alert', dependencies=[Depends(require_login)])
def dart_alert_page(request: Request):
    return render(request, 'stock/dart_alert.html')


# ── API ───────────────────────────────────────────────────────────────────

@router.get('/api/dart_alert/watchlist', dependencies=[Depends(api_require_login)])
def api_watchlist_get():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, name, added_at FROM dart_alert_watchlist ORDER BY id")
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        if r.get('added_at'):
            r['added_at'] = r['added_at'].strftime('%Y-%m-%d')
    return {'ok': True, 'watchlist': rows}


@router.post('/api/dart_alert/watchlist', dependencies=[Depends(api_require_login)])
def api_watchlist_add(request: Request, body: dict = Body(default={})):
    code = body.get('code', '').strip().zfill(6)[:6]
    name = body.get('name', '').strip()[:100]
    if not code or not name:
        return JSONResponse({'ok': False, 'error': '종목코드와 종목명을 입력하세요'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO dart_alert_watchlist (code, name) VALUES (%s, %s)",
                (code, name)
            )
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


@router.delete('/api/dart_alert/watchlist/{code}', dependencies=[Depends(api_require_login)])
def api_watchlist_delete(code: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dart_alert_watchlist WHERE code = %s", (code,))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


@router.get('/api/dart_alert/history', dependencies=[Depends(api_require_login)])
def api_history(request: Request):
    """최근 공시 발송 이력. ?days=7&code=005930"""
    days = int(request.query_params.get('days', '7'))
    code = request.query_params.get('code', '').strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if code:
                cur.execute(
                    "SELECT h.code, w.name, h.disclose_date, h.title, h.category, h.sent_at "
                    "FROM dart_alert_history h "
                    "LEFT JOIN dart_alert_watchlist w ON w.code = h.code "
                    "WHERE h.code = %s AND h.sent_at >= NOW() - INTERVAL %s DAY "
                    "ORDER BY h.sent_at DESC LIMIT 200",
                    (code, days)
                )
            else:
                cur.execute(
                    "SELECT h.code, w.name, h.disclose_date, h.title, h.category, h.sent_at "
                    "FROM dart_alert_history h "
                    "LEFT JOIN dart_alert_watchlist w ON w.code = h.code "
                    "WHERE h.sent_at >= NOW() - INTERVAL %s DAY "
                    "ORDER BY h.sent_at DESC LIMIT 200",
                    (days,)
                )
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        if r.get('sent_at'):
            r['sent_at'] = r['sent_at'].strftime('%Y-%m-%d %H:%M')
    return {'ok': True, 'items': rows}


@router.get('/api/dart_alert/watchlist_history', dependencies=[Depends(api_require_login)])
def api_watchlist_history(request: Request):
    """관심 종목 전체의 최근 공시 합산 반환 (기본 화면용, 최근 30일)."""
    days = int(request.query_params.get('days', '30'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, name FROM dart_alert_watchlist ORDER BY id")
            watchlist = cur.fetchall()
    finally:
        conn.close()

    if not watchlist:
        return {'ok': True, 'items': []}

    try:
        from XGBoost_v2.dart_client import get_recent_disclosures
    except ImportError:
        return {'ok': True, 'items': []}

    all_items = []
    for stock in watchlist:
        code, name = stock['code'], stock['name']
        disclosures = get_recent_disclosures(code, days=days)
        for d in disclosures:
            raw = d.get('date', '')
            date_fmt = f'{raw[:4]}-{raw[4:6]}-{raw[6:]}' if len(raw) == 8 else raw
            all_items.append({
                'code':          code,
                'name':          name,
                'disclose_date': raw,
                'title':         d.get('title', ''),
                'category':      d.get('category', 'neutral'),
                'sent_at':       date_fmt,
                'rcept_no':      d.get('rcept_no', ''),
            })

    # 최근 순 정렬
    all_items.sort(key=lambda x: x['disclose_date'], reverse=True)
    return {'ok': True, 'items': all_items[:200]}


@router.get('/api/dart_alert/stock_history', dependencies=[Depends(api_require_login)])
def api_stock_history(request: Request):
    """특정 종목의 DART 공시 이력 직접 조회 (캐시 우회, 최대 180일)."""
    import os, requests as req
    from datetime import datetime, timedelta

    code = request.query_params.get('code', '').strip().zfill(6)[:6]
    days = int(request.query_params.get('days', '180'))
    if not code:
        return JSONResponse({'ok': False, 'error': 'code 필요'}, status_code=400)

    DART_KEY = os.getenv('DART_API_KEY', '')
    if not DART_KEY:
        return {'ok': True, 'items': [], 'notice': 'DART_API_KEY 없음'}

    try:
        from XGBoost_v2.dart_client import _load_corp_map, _classify_report
    except ImportError as e:
        logger.error(f'[dart_alert] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)

    corp_map  = _load_corp_map()
    corp_code = corp_map.get(code)
    if not corp_code:
        return {'ok': True, 'items': []}

    # 종목명 조회
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM dart_alert_watchlist WHERE code = %s", (code,))
            row = cur.fetchone()
            name = row['name'] if row else code
    finally:
        conn.close()

    try:
        end   = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        url = (
            'https://opendart.fss.or.kr/api/list.json'
            f'?crtfc_key={DART_KEY}&corp_code={corp_code}'
            f'&bgn_de={start}&end_de={end}&page_count=100'
        )
        r    = req.get(url, timeout=8)
        data = r.json()
        items = data.get('list') or []
        result = []
        for it in items:
            d = it.get('rcept_dt', '')
            date_fmt = f'{d[:4]}-{d[4:6]}-{d[6:]}' if len(d) == 8 else d
            result.append({
                'code':          code,
                'name':          name,
                'disclose_date': d,
                'title':         it.get('report_nm', ''),
                'category':      _classify_report(it.get('report_nm', '')),
                'sent_at':       date_fmt,
                'rcept_no':      it.get('rcept_no', ''),
            })
        return {'ok': True, 'items': result}
    except Exception as e:
        logger.error(f'[dart_alert/stock_history] {e}')
        logger.error(f'[dart_alert] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)


@router.post('/api/dart_alert/run', dependencies=[Depends(api_require_login)])
def api_run():
    """수동 즉시 공시 체크."""
    try:
        count = check_and_notify()
        return {'ok': True, 'new': count,
                'run_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    except Exception as e:
        logger.error(f'[dart_alert/run] {e}')
        logger.error(f'[dart_alert] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
