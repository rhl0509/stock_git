from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from database.db_connection import get_db_connection
from routes.utils import api_require_login, require_login_smart
import requests, re
import logging

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_login_smart)])


def sync_kr_stocks():
    """네이버 금융에서 KRX 전체 종목 수집 → DB 저장"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        stocks = []

        for sosok, market, suffix in [('0', 'KOSPI', '.KS'), ('1', 'KOSDAQ', '.KQ')]:
            for page in range(1, 60):
                url = 'https://finance.naver.com/sise/sise_market_sum.nhn?sosok=' + sosok + '&page=' + str(page)
                r = requests.get(url, headers=headers, timeout=10)
                r.encoding = 'euc-kr'
                matches = re.findall(
                    r'href="/item/main\.naver\?code=([0-9]+)"[^>]*>([^<]+)</a>',
                    r.text
                )
                if not matches:
                    break
                for code, name in matches:
                    stocks.append((code, name.strip(), market, code + suffix))

        if not stocks:
            logger.error("[KR_STOCKS] 수집 실패")
            return 0

        seen = set()
        unique = []
        for row in stocks:
            if row[0] not in seen:
                seen.add(row[0])
                unique.append(row)

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM kr_stocks")
                cursor.executemany(
                    "INSERT INTO kr_stocks (code, name, market, ticker) VALUES (%s,%s,%s,%s)",
                    unique
                )
            conn.commit()
            from datetime import datetime
            logger.info(f"[KR_STOCKS] 동기화 완료: {len(unique)}개 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
            return len(unique)
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"[KR_STOCKS] 동기화 실패: {e}")
        return 0


@router.get('/search-stock-kr')
def search_kr_stock(request: Request):
    q = request.query_params.get('q', '').strip()
    if not q:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT code, name, market, ticker
                FROM kr_stocks
                WHERE name LIKE %s OR code LIKE %s
                ORDER BY
                    CASE WHEN name = %s OR code = %s THEN 0      -- 정확히 일치
                         WHEN name LIKE %s            THEN 1      -- 이름 접두사
                         ELSE 2 END,                             -- 이름 부분일치
                    LENGTH(name)
                LIMIT 10
            """, (f'%{q}%', f'{q}%', q, q, f'{q}%'))
            return cursor.fetchall()
    finally:
        conn.close()


@router.post('/sync-kr-stocks', dependencies=[Depends(api_require_login)])
def sync_stocks():
    count = sync_kr_stocks()
    if count:
        return {"status": "ok", "count": count}
    return JSONResponse({"error": "동기화 실패"}, status_code=500)
