"""routes/price_alert.py — 관심 종목 가격 알림 (목표가/손절가 도달 시 카카오톡)."""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from routes.utils import api_require_login, require_login, get_user_no
from templates_config import render

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    user_no      INT           NOT NULL DEFAULT 1,
                    code         CHAR(6)       NOT NULL,
                    name         VARCHAR(100)  NOT NULL,
                    target_price INT,
                    stop_price   INT,
                    note         VARCHAR(200),
                    active       TINYINT(1)    DEFAULT 1,
                    created_at   DATETIME      DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user (user_no)
                )
            """)
            # 기존 테이블 마이그레이션: user_no 컬럼 없으면 추가 (기존 행은 1번 회원 소유로 귀속)
            cur.execute("SHOW COLUMNS FROM price_alerts LIKE 'user_no'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE price_alerts "
                            "ADD COLUMN user_no INT NOT NULL DEFAULT 1 AFTER id, "
                            "ADD INDEX idx_user (user_no)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS price_alert_log (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    alert_id   INT          NOT NULL,
                    code       CHAR(6)      NOT NULL,
                    name       VARCHAR(100),
                    kind       VARCHAR(10)  NOT NULL,
                    price      INT          NOT NULL,
                    sent_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _get_price(code: str) -> int | None:
    try:
        from kiwoom_client import kiwoom
        d = kiwoom.get_best_price(code)
        if d and d.get('price'):
            return int(d['price'])
    except Exception:
        pass
    try:
        import requests as req
        r = req.get(
            f'https://m.stock.naver.com/api/stock/{code}/basic',
            timeout=5, headers={'User-Agent': 'Mozilla/5.0'}
        )
        p = r.json().get('closePrice', '')
        if p:
            return int(str(p).replace(',', ''))
    except Exception:
        pass
    return None


def check_price_alerts() -> int:
    """모든 활성 알림 가격 체크 → 도달 시 카카오톡 발송. 발송 건수 반환."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM price_alerts WHERE active = 1"
            )
            alerts = cur.fetchall()
    finally:
        conn.close()

    if not alerts:
        return 0

    sent = 0
    for alert in alerts:
        price = _get_price(alert['code'])
        if not price:
            continue

        hit_kind = None
        if alert['target_price'] and price >= alert['target_price']:
            hit_kind = 'target'
        elif alert['stop_price'] and price <= alert['stop_price']:
            hit_kind = 'stop'

        if not hit_kind:
            continue

        # 오늘 이미 같은 알림 발송했으면 스킵
        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    "SELECT id FROM price_alert_log "
                    "WHERE alert_id = %s AND kind = %s AND DATE(sent_at) = CURDATE()",
                    (alert['id'], hit_kind)
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    "INSERT INTO price_alert_log (alert_id, code, name, kind, price) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (alert['id'], alert['code'], alert['name'], hit_kind, price)
                )
            conn2.commit()
        finally:
            conn2.close()

        try:
            from notify.send import send_message_to_self
            emoji = '🎯' if hit_kind == 'target' else '🚨'
            label = '목표가 도달' if hit_kind == 'target' else '손절가 하회'
            threshold = alert['target_price'] if hit_kind == 'target' else alert['stop_price']
            note = f"\n메모: {alert['note']}" if alert.get('note') else ''
            msg = (
                f"{emoji} 가격 알림 — {label}\n"
                f"{alert['name']}({alert['code']})\n"
                f"현재가: {price:,}원  |  기준가: {threshold:,}원{note}\n"
                f"{datetime.now().strftime('%H:%M')}"
            )
            port = int(os.getenv('FLASK_PORT', '5000'))
            send_message_to_self(msg, link_url=f'http://localhost:{port}/price_alert')
            sent += 1
            logger.info(f'[price_alert] {alert["name"]} {label}: {price:,}')
        except Exception as e:
            logger.error(f'[price_alert] 카카오 발송 실패: {e}')

    return sent


# ── 페이지 ────────────────────────────────────────────────────────────────

@router.get('/price_alert', dependencies=[Depends(require_login)])
def price_alert_page(request: Request):
    return render(request, 'stock/price_alert.html')


# ── API ───────────────────────────────────────────────────────────────────

@router.get('/api/price_alerts', dependencies=[Depends(api_require_login)])
def api_list(request: Request):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM price_alerts WHERE user_no = %s ORDER BY active DESC, id DESC",
                (get_user_no(request),)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        if r.get('created_at'):
            r['created_at'] = r['created_at'].strftime('%Y-%m-%d')
    return {'ok': True, 'alerts': rows}


@router.post('/api/price_alerts', dependencies=[Depends(api_require_login)])
def api_add(request: Request, body: dict = Body(default={})):
    code   = body.get('code', '').strip().zfill(6)[:6]
    name   = body.get('name', '').strip()[:100]
    target = body.get('target_price') or None
    stop   = body.get('stop_price') or None
    note   = body.get('note', '').strip()[:200] or None
    if not code or not name:
        return JSONResponse({'ok': False, 'error': '종목코드와 종목명을 입력하세요'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO price_alerts (user_no, code, name, target_price, stop_price, note) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (get_user_no(request), code, name, target, stop, note)
            )
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


@router.put('/api/price_alerts/{alert_id}', dependencies=[Depends(api_require_login)])
def api_update(alert_id: int, request: Request, body: dict = Body(default={})):
    fields, vals = [], []
    for col in ('target_price', 'stop_price', 'note', 'active'):
        if col in body:
            fields.append(f'{col} = %s')
            vals.append(body[col] if body[col] != '' else None)
    if not fields:
        return JSONResponse({'ok': False, 'error': '변경 항목 없음'}, status_code=400)
    vals += [alert_id, get_user_no(request)]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE price_alerts SET {', '.join(fields)} WHERE id = %s AND user_no = %s",
                vals
            )
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


@router.delete('/api/price_alerts/{alert_id}', dependencies=[Depends(api_require_login)])
def api_delete(alert_id: int, request: Request):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM price_alerts WHERE id = %s AND user_no = %s",
                        (alert_id, get_user_no(request)))
        conn.commit()
    finally:
        conn.close()
    return {'ok': True}


@router.get('/api/price_alerts/log', dependencies=[Depends(api_require_login)])
def api_log(request: Request):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT l.* FROM price_alert_log l "
                "JOIN price_alerts a ON a.id = l.alert_id "
                "WHERE a.user_no = %s "
                "ORDER BY l.sent_at DESC LIMIT 100",
                (get_user_no(request),)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        if r.get('sent_at'):
            r['sent_at'] = r['sent_at'].strftime('%Y-%m-%d %H:%M')
    return {'ok': True, 'log': rows}


@router.post('/api/price_alerts/run', dependencies=[Depends(api_require_login)])
def api_run():
    try:
        sent = check_price_alerts()
        return {'ok': True, 'sent': sent}
    except Exception as e:
        logger.error(f'[price_alert/run] {e}', exc_info=True)
        return JSONResponse({'ok': False, 'error': '알림 체크 중 오류가 발생했습니다.'}, status_code=500)
