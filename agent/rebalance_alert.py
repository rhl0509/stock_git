"""agent/rebalance_alert.py — 포트폴리오 리밸런싱 알림.

보유 종목의 현재 비중이 목표 비중 대비 ±threshold% 이탈 시 카톡 알림.
스케줄: 평일 16:00 (장 마감 후).
"""
from __future__ import annotations
import logging
from database.db_connection import get_db_connection

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 5.0  # 목표 비중 대비 ±5% 이탈 시 알림


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rebalance_targets (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    user_no     INT NOT NULL,
                    stock_code  VARCHAR(20) NOT NULL,
                    target_pct  DECIMAL(5,2) NOT NULL,
                    threshold   DECIMAL(5,2) DEFAULT 5.0,
                    created_at  DATETIME DEFAULT NOW(),
                    UNIQUE KEY uk_user_code (user_no, stock_code)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()

try:
    _ensure_table()
except Exception:
    pass


def _get_current_prices(codes: list) -> dict:
    import requests as _req
    prices = {}
    for code in codes:
        try:
            r = _req.get(
                f'https://m.stock.naver.com/api/stock/{code}/basic',
                headers={'User-Agent': 'Mozilla/5.0'}, timeout=4
            )
            raw = r.json()
            p = raw.get('closePrice') or raw.get('currentPrice')
            if p:
                prices[code] = float(str(p).replace(',', ''))
        except Exception:
            pass
    return prices


def run(send_kakao: bool = True) -> dict:
    logger.info('[rebalance] 리밸런싱 알림 체크 시작')
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # 리밸런싱 목표가 설정된 사용자별로 처리
            cur.execute("""
                SELECT rt.user_no, rt.stock_code, rt.target_pct, rt.threshold,
                       sh.quantity, sh.avg_price, sh.name
                FROM rebalance_targets rt
                JOIN stock_holdings sh ON sh.code = rt.stock_code AND sh.member_id = rt.user_no
            """)
            rows = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f'[rebalance] DB 조회 실패: {e}')
        return {'ok': False, 'error': str(e)}

    if not rows:
        logger.info('[rebalance] 설정된 목표 비중 없음')
        return {'ok': True, 'alerts': 0}

    # 사용자별 그룹핑
    from collections import defaultdict
    user_rows: dict = defaultdict(list)
    for r in rows:
        user_rows[r['user_no']].append(r)

    alerts_sent = 0
    for user_no, items in user_rows.items():
        codes = [i['stock_code'] for i in items]
        prices = _get_current_prices(codes)

        # 포트폴리오 총가치 계산
        total_val = sum(
            (prices.get(i['stock_code'], i['avg_price']) * i['quantity'])
            for i in items
        )
        if total_val <= 0:
            continue

        drifts = []
        for item in items:
            cur_price = prices.get(item['stock_code'], item['avg_price'])
            cur_val   = cur_price * item['quantity']
            cur_pct   = cur_val / total_val * 100
            target    = float(item['target_pct'])
            drift     = cur_pct - target
            threshold = float(item.get('threshold') or DEFAULT_THRESHOLD)
            if abs(drift) >= threshold:
                drifts.append({
                    'name':       item.get('name', item['stock_code']),
                    'code':       item['stock_code'],
                    'cur_pct':    round(cur_pct, 1),
                    'target_pct': round(target, 1),
                    'drift':      round(drift, 1),
                })

        if not drifts and not send_kakao:
            continue
        if not drifts:
            continue

        msg_lines = ['⚖️ 포트폴리오 리밸런싱 필요\n']
        for d in drifts:
            direction = '▲ 과중' if d['drift'] > 0 else '▼ 부족'
            msg_lines.append(
                f"{d['name']} ({d['code']})\n"
                f"  현재 {d['cur_pct']}% → 목표 {d['target_pct']}% ({direction} {abs(d['drift'])}%p)"
            )
        msg = '\n'.join(msg_lines)

        if send_kakao:
            try:
                from notify.send import send_message_to_self
                send_message_to_self(msg)
                alerts_sent += 1
            except Exception as e:
                logger.warning(f'[rebalance] 카톡 발송 실패: {e}')

        # 이메일도 발송
        try:
            from notify.email_send import send_email_if_enabled
            send_email_if_enabled('⚖️ 리밸런싱 알림', msg)
        except Exception:
            pass

    logger.info(f'[rebalance] 완료 — {alerts_sent}건 알림')
    return {'ok': True, 'alerts': alerts_sent}


if __name__ == '__main__':
    import sys
    result = run(send_kakao='--no-kakao' not in sys.argv)
    print(result)
