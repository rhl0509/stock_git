"""routes/watchlist.py — 관심종목 그룹 관리."""
import asyncio
import logging
import requests as _req

from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse
from routes.utils import get_login_user, login_required_response
from database.db_connection import get_db_connection

router = APIRouter()
logger = logging.getLogger(__name__)

_NAVER_HDR = {'User-Agent': 'Mozilla/5.0'}


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS watchlist_groups (
                    id        INT AUTO_INCREMENT PRIMARY KEY,
                    user_no   INT NOT NULL,
                    name      VARCHAR(100) NOT NULL,
                    created_at DATETIME DEFAULT NOW(),
                    INDEX idx_user (user_no)
                ) CHARACTER SET utf8mb4
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS watchlist_items (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    group_id    INT NOT NULL,
                    user_no     INT NOT NULL,
                    stock_code  VARCHAR(20) NOT NULL,
                    stock_name  VARCHAR(100),
                    memo        VARCHAR(255),
                    created_at  DATETIME DEFAULT NOW(),
                    UNIQUE KEY uk_group_code (group_id, stock_code),
                    INDEX idx_user (user_no)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()

try:
    _ensure_table()
except Exception:
    pass


def _fetch_price(code: str) -> tuple[float | None, float | None]:
    """(current_price, change_pct) — 실패 시 (None, None)."""
    try:
        r   = _req.get(f'https://m.stock.naver.com/api/stock/{code}/basic',
                       headers=_NAVER_HDR, timeout=3)
        raw = r.json()
        p   = raw.get('closePrice') or raw.get('currentPrice')
        c   = raw.get('fluctuationsRatio') or raw.get('changeRate')
        price = float(str(p).replace(',', '')) if p else None
        chg   = float(str(c).replace(',', '').replace('+', '')) if c else None
        return price, chg
    except Exception:
        return None, None


@router.get('/api/watchlist/groups')
def get_groups(request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, created_at FROM watchlist_groups WHERE user_no=%s ORDER BY id",
                (user['user_no'],)
            )
            groups = cur.fetchall()
            for g in groups:
                cur.execute("SELECT COUNT(*) AS cnt FROM watchlist_items WHERE group_id=%s", (g['id'],))
                g['count'] = cur.fetchone()['cnt']
                if hasattr(g.get('created_at'), 'isoformat'):
                    g['created_at'] = g['created_at'].isoformat()
        return JSONResponse({'ok': True, 'groups': groups})
    except Exception as e:
        logger.error(f"[watchlist/groups] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post('/api/watchlist/groups')
def create_group(request: Request, body: dict = Body(default={})):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    name = (body.get('name') or '').strip()
    if not name:
        return JSONResponse({'ok': False, 'error': '그룹명 필요'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO watchlist_groups (user_no, name) VALUES (%s,%s)",
                (user['user_no'], name)
            )
            conn.commit()
            return JSONResponse({'ok': True, 'id': cur.lastrowid})
    except Exception as e:
        logger.error(f"[watchlist/create_group] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.delete('/api/watchlist/groups/{group_id}')
def delete_group(group_id: int, request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist_items  WHERE group_id=%s AND user_no=%s", (group_id, user['user_no']))
            cur.execute("DELETE FROM watchlist_groups WHERE id=%s       AND user_no=%s", (group_id, user['user_no']))
        conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f"[watchlist/delete_group] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.get('/api/watchlist/{group_id}/items')
async def get_items(group_id: int, request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, stock_code, stock_name, memo FROM watchlist_items "
                "WHERE group_id=%s AND user_no=%s ORDER BY id",
                (group_id, user['user_no'])
            )
            items = cur.fetchall()
    except Exception as e:
        logger.error(f"[watchlist/items] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()

    # 가격 병렬 조회 — blocking I/O를 스레드풀로 분산
    async def _price_task(item):
        price, chg = await asyncio.to_thread(_fetch_price, item['stock_code'])
        item['current_price'] = price
        item['change_pct']    = chg

    await asyncio.gather(*[_price_task(item) for item in items])
    return JSONResponse({'ok': True, 'items': items})


@router.post('/api/watchlist/{group_id}/items')
def add_item(group_id: int, request: Request, body: dict = Body(default={})):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    code = (body.get('stock_code') or '').strip()
    if not code:
        return JSONResponse({'ok': False, 'error': '종목코드 필요'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO watchlist_items (group_id, user_no, stock_code, stock_name, memo) "
                "VALUES (%s,%s,%s,%s,%s)",
                (group_id, user['user_no'], code, body.get('stock_name', code), body.get('memo', ''))
            )
            conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f"[watchlist/add_item] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.delete('/api/watchlist/items/{item_id}')
def delete_item(item_id: int, request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watchlist_items WHERE id=%s AND user_no=%s", (item_id, user['user_no']))
        conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f"[watchlist/delete_item] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()
