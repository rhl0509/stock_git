"""routes/dividend.py — 배당 캘린더 및 수령 기록."""
import logging
from decimal import Decimal
from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse
from routes.utils import get_login_user, login_required_response
from database.db_connection import get_db_connection

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dividend_records (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    user_no      INT NOT NULL,
                    stock_code   VARCHAR(20) NOT NULL,
                    stock_name   VARCHAR(100),
                    ex_div_date  DATE,
                    pay_date     DATE,
                    dividend_per_share DECIMAL(12,2),
                    quantity     INT DEFAULT 0,
                    total_amount DECIMAL(14,2),
                    memo         VARCHAR(255),
                    created_at   DATETIME DEFAULT NOW(),
                    INDEX idx_user (user_no),
                    INDEX idx_ex_date (ex_div_date)
                ) CHARACTER SET utf8mb4
            """)
        conn.commit()
    finally:
        conn.close()

try:
    _ensure_table()
except Exception:
    pass


def _to_int(v) -> int:
    try:
        return int(float(str(v).replace(',', '').strip() or 0))
    except (ValueError, TypeError):
        return 0


def _to_decimal(v) -> Decimal:
    try:
        return Decimal(str(v).replace(',', '').strip() or '0')
    except (ValueError, TypeError, ArithmeticError):
        return Decimal('0')


def _serialize_rows(rows):
    """DB 행을 JSON 직렬화 가능하게 변환 (DATE/DATETIME → ISO 문자열, DECIMAL → float)."""
    for r in rows:
        for k, v in r.items():
            if hasattr(v, 'isoformat'):
                r[k] = v.isoformat()
            elif isinstance(v, Decimal):
                r[k] = float(v)
    return rows


@router.get('/api/dividend')
def get_dividends(request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM dividend_records WHERE user_no=%s ORDER BY ex_div_date DESC",
                (user['user_no'],)
            )
            rows = _serialize_rows(cur.fetchall())
        return JSONResponse({'ok': True, 'records': rows})
    except Exception as e:
        logger.error(f"[dividend/get] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.post('/api/dividend')
def add_dividend(request: Request, body: dict = Body(default={})):
    user = get_login_user(request)
    if not user:
        return login_required_response()

    code = str(body.get('stock_code') or '').strip().zfill(6)[:6]
    if not code.isdigit():
        return JSONResponse({'ok': False, 'error': '종목코드(숫자 6자리)를 입력하세요.'}, status_code=400)

    ex_div_date = body.get('ex_div_date') or None
    pay_date    = body.get('pay_date') or None
    dps         = _to_decimal(body.get('dividend_per_share'))
    quantity    = _to_int(body.get('quantity'))
    total       = _to_decimal(body.get('total_amount')) or (dps * quantity)

    # 전부 빈값(금액 0 + 날짜 없음)이면 의미 없는 레코드 → 거부
    if total <= 0 and dps <= 0 and not ex_div_date and not pay_date:
        return JSONResponse(
            {'ok': False, 'error': '주당배당금·수령금액·날짜 중 최소 하나는 입력해야 합니다.'},
            status_code=400)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 종목명이 비면 kr_stocks 에서 보충 (stock_holdings 추가와 동일 정책)
            name = str(body.get('stock_name') or '').strip()
            if not name or name == code:
                cur.execute("SELECT name FROM kr_stocks WHERE code=%s", (code,))
                row = cur.fetchone()
                name = row['name'] if row else code

            cur.execute("""
                INSERT INTO dividend_records
                    (user_no, stock_code, stock_name, ex_div_date, pay_date,
                     dividend_per_share, quantity, total_amount, memo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                user['user_no'], code, name,
                ex_div_date, pay_date, dps, quantity, total,
                body.get('memo', ''),
            ))
            conn.commit()
            return JSONResponse({'ok': True, 'id': cur.lastrowid, 'stock_name': name})
    except Exception as e:
        logger.error(f"[dividend/add] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.delete('/api/dividend/{record_id}')
def delete_dividend(record_id: int, request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM dividend_records WHERE id=%s AND user_no=%s",
                (record_id, user['user_no'])
            )
        conn.commit()
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f"[dividend/delete] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.get('/api/dividend/autofill/{code}')
def dividend_autofill(code: str, request: Request):
    """종목코드만으로 배당 기록 폼 자동완성 데이터 반환.
    - 종목명: kr_stocks
    - 보유수량: stock_holdings
    - 주당배당금/배당락일: yfinance 배당 이력 (최근 8건 포함)
    - 지급일: 배당락일 + 1개월 추정치 (수정 가능 안내)
    """
    user = get_login_user(request)
    if not user:
        return login_required_response()
    code = code.strip().zfill(6)[:6]
    if not code.isdigit():
        return JSONResponse({'ok': False, 'error': '숫자 6자리 코드만 지원합니다'}, status_code=400)

    name, quantity = '', 0
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM kr_stocks WHERE code=%s", (code,))
            row = cur.fetchone()
            if row:
                name = row['name']
            cur.execute(
                "SELECT quantity FROM stock_holdings WHERE member_id=%s AND code=%s",
                (user['user_no'], code)
            )
            row = cur.fetchone()
            if row:
                quantity = int(row['quantity'] or 0)
    finally:
        conn.close()

    history = []
    try:
        import yfinance as yf
        from datetime import timedelta
        for suffix in ('.KS', '.KQ'):
            div = yf.Ticker(code + suffix).dividends
            if div is not None and len(div):
                for dt, amt in div.tail(8).items():
                    ex_date = dt.strftime('%Y-%m-%d')
                    pay_est = (dt + timedelta(days=30)).strftime('%Y-%m-%d')
                    history.append({'ex_div_date': ex_date,
                                    'dividend_per_share': round(float(amt), 2),
                                    'pay_date_est': pay_est})
                break
    except Exception as e:
        logger.warning(f"[dividend/autofill] {code} 배당 이력 조회 실패: {e}")

    history.reverse()  # 최신순
    latest = history[0] if history else None
    return JSONResponse({
        'ok': True, 'code': code, 'name': name, 'quantity': quantity,
        'latest': latest, 'history': history,
    })


# ─────────────────────────────────────────────────────────────────
# 키움 연동: 보유종목 기반 배당 자동 인식
# ─────────────────────────────────────────────────────────────────

_DIV_HIST_CACHE: dict = {}   # code → {'ts': ..., 'divs': [(date, amt), ...]}
_DIV_HIST_TTL = 6 * 3600


def _fetch_div_history(code: str) -> list:
    """yfinance 배당 이력 [(datetime, float), ...] — 6시간 캐시."""
    import time as _t
    cached = _DIV_HIST_CACHE.get(code)
    if cached and _t.time() - cached['ts'] < _DIV_HIST_TTL:
        return cached['divs']
    divs = []
    try:
        import yfinance as yf
        for suffix in ('.KS', '.KQ'):
            s = yf.Ticker(code + suffix).dividends
            if s is not None and len(s):
                divs = [(dt.to_pydatetime().replace(tzinfo=None), float(amt)) for dt, amt in s.items()]
                break
    except Exception as e:
        logger.warning(f"[dividend/kiwoom] {code} 배당 이력 실패: {e}")
    _DIV_HIST_CACHE[code] = {'ts': _t.time(), 'divs': divs}
    return divs


# ── KIS 확정 배당(예탁원정보) 보강 ──────────────────────────────────
# yfinance 가 주는 배당락 이벤트(기존 dedup 키 유지)에 KIS 확정 지급일·주당
# 배당금을 덧씌운다. KIS 키 미설정·조회 실패 시 조용히 yfinance 추정으로 폴백.
_KIS_SINGLETON = "uninit"          # "uninit" | KISClient | None
_KIS_DIV_CACHE: dict = {}          # code → {'ts': float, 'events': [...]}
_KIS_DIV_TTL = 12 * 3600


def _get_kis():
    """KISClient 싱글톤. 키 미설정/토큰 발급 실패 시 None 반환(폴백)."""
    global _KIS_SINGLETON
    if _KIS_SINGLETON == "uninit":
        try:
            from dividend_service import KISClient
            client = KISClient()
            client.get_token()          # 발급 가능 여부 즉시 확인
            _KIS_SINGLETON = client
        except Exception as e:
            logger.warning(f"[dividend/kis] KIS 비활성화 — yfinance 폴백: {e}")
            _KIS_SINGLETON = None
    return _KIS_SINGLETON


def _kis_dividends(code: str) -> list:
    """KIS 확정 배당 이벤트 [{'record_dt': datetime|None, 'pay_date': str|None, 'dps': float}]
    — 12시간 캐시. 종목당 1회 호출."""
    import time as _t
    from datetime import datetime as _dt2, timedelta as _td2
    code = code.zfill(6)
    cached = _KIS_DIV_CACHE.get(code)
    if cached and _t.time() - cached['ts'] < _KIS_DIV_TTL:
        return cached['events']
    events = []
    kis = _get_kis()
    if kis:
        try:
            f_dt = (_dt2.now() - _td2(days=400)).strftime('%Y%m%d')
            t_dt = (_dt2.now() + _td2(days=400)).strftime('%Y%m%d')
            for s in kis.fetch_dividend_kr(symbol=code, from_date=f_dt, to_date=t_dt):
                rd = s.get('record_date')
                events.append({
                    'record_dt': _dt2.strptime(rd, '%Y-%m-%d') if rd else None,
                    'pay_date':  s.get('pay_date'),
                    'dps':       s.get('dps') or 0,
                })
        except Exception as e:
            logger.warning(f"[dividend/kis] {code} 배당일정 조회 실패: {e}")
    _KIS_DIV_CACHE[code] = {'ts': _t.time(), 'events': events}
    return events


def _enrich_kr_dividend(code: str, ex_dt, amt: float, qty: float) -> dict:
    """yfinance 배당락 이벤트(ex_dt: datetime)를 KIS 확정값으로 보강.
    배당기준일이 배당락일과 ±10일 이내인 KIS 건을 매칭한다.
    반환: {'pay_date': str, 'dps': float, 'total': int, 'confirmed': bool}"""
    from datetime import timedelta
    pay_date  = (ex_dt + timedelta(days=30)).strftime('%Y-%m-%d')   # 기본 추정
    dps       = round(amt, 2)
    confirmed = False
    for ev in _kis_dividends(code):
        rd = ev.get('record_dt')
        if rd and abs((rd - ex_dt).days) <= 10:
            if ev.get('dps'):
                dps = round(ev['dps'], 2)
            if ev.get('pay_date'):
                pay_date  = ev['pay_date']
                confirmed = True
            break
    return {'pay_date': pay_date, 'dps': dps, 'total': round(dps * qty), 'confirmed': confirmed}


def _get_holdings_for(user_no: int) -> tuple[list, str]:
    """키움 실시간 보유종목 우선, 실패 시 DB(stock_holdings) 폴백. (holdings, source) 반환."""
    try:
        from kiwoom_client import kiwoom
        from routes.utils import is_owner_user_no
        # 키움 실보유는 주인 단일계좌. 소유자만 키움 보유를 쓰고, 그 외 회원은 DB 폴백.
        if is_owner_user_no(user_no) and kiwoom.get_login_state() == 1:
            raw = kiwoom.get_account_holdings()
            if raw:
                holdings = []
                for h in raw:
                    code = (h.get('code') or '').strip().lstrip('A')
                    try:
                        qty = int(float(str(h.get('quantity') or 0).replace(',', '')))
                    except ValueError:
                        qty = 0
                    if code and qty > 0:
                        holdings.append({'code': code.zfill(6), 'name': (h.get('name') or code).strip(), 'quantity': qty})
                if holdings:
                    return holdings, 'kiwoom'
    except Exception as e:
        logger.warning(f"[dividend/kiwoom] 키움 조회 실패, DB 폴백: {e}")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, name, quantity FROM stock_holdings WHERE member_id=%s AND quantity > 0",
                (user_no,)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return ([{'code': r['code'].zfill(6), 'name': r['name'], 'quantity': int(r['quantity'])} for r in rows],
            'db')


@router.get('/api/dividend/kiwoom/preview')
def kiwoom_dividend_preview(request: Request):
    """키움 보유종목 기반 배당 현황:
    - expected: 종목별 연간 예상 배당 (TTM 주당배당 합 × 보유수량) + 시가배당률 + 다음 배당 예상일
    - candidates: 최근 12개월 배당락 지난 배당 → 자동 기록 후보 (기존 기록 중복 표시)
    """
    user = get_login_user(request)
    if not user:
        return login_required_response()

    holdings, source = _get_holdings_for(user['user_no'])
    if not holdings:
        return JSONResponse({'ok': False,
                             'error': '보유종목이 없습니다. 포트폴리오에서 키움 동기화를 먼저 실행하세요.'},
                            status_code=404)

    # 기존 기록 (중복 방지 키: 종목코드+배당락일)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stock_code, ex_div_date FROM dividend_records WHERE user_no=%s AND ex_div_date IS NOT NULL",
                (user['user_no'],)
            )
            existing = {(r['stock_code'], r['ex_div_date'].isoformat()) for r in cur.fetchall()}
    finally:
        conn.close()

    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta
    now      = datetime.now()
    one_year = now - timedelta(days=365)

    codes = [h['code'] for h in holdings]
    with ThreadPoolExecutor(max_workers=6) as ex:
        hist_map = dict(zip(codes, ex.map(_fetch_div_history, codes)))

    # 현재가 (시가배당률 계산용) — kiwoom 모듈의 네이버 시세 재사용
    def _price(code):
        try:
            from routes.kiwoom import _fetch_naver_price
            return _fetch_naver_price(code)
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=6) as ex:
        price_map = dict(zip(codes, ex.map(_price, codes)))

    expected, candidates = [], []
    for h in holdings:
        code, qty = h['code'], h['quantity']
        divs = hist_map.get(code, [])
        ttm  = [(dt, amt) for dt, amt in divs if dt >= one_year]
        ttm_dps = round(sum(a for _, a in ttm), 2)
        price   = price_map.get(code)

        # 다음 배당 예상일: 마지막 배당락일 + 배당 간격 중앙값
        next_est = None
        if len(divs) >= 2:
            gaps = sorted((divs[i][0] - divs[i-1][0]).days for i in range(max(1, len(divs)-6), len(divs)))
            median_gap = gaps[len(gaps)//2]
            next_est = (divs[-1][0] + timedelta(days=median_gap)).strftime('%Y-%m-%d')

        expected.append({
            'code': code, 'name': h['name'], 'quantity': qty,
            'ttm_dps': ttm_dps,
            'annual_est': round(ttm_dps * qty),
            'yield_pct': round(ttm_dps / price * 100, 2) if price and ttm_dps else None,
            'pay_count_1y': len(ttm),
            'next_ex_est': next_est,
        })

        # 자동 기록 후보: 최근 12개월 배당락 지난 건 (KR은 KIS 확정값 우선)
        for dt, amt in ttm:
            if dt > now:
                continue
            ex_date = dt.strftime('%Y-%m-%d')
            enr = _enrich_kr_dividend(code, dt, amt, qty)
            candidates.append({
                'code': code, 'name': h['name'], 'quantity': qty,
                'ex_div_date': ex_date,
                'pay_date_est': enr['pay_date'],
                'dividend_per_share': enr['dps'],
                'total_amount': enr['total'],
                'confirmed': enr['confirmed'],
                'already': (code, ex_date) in existing,
            })

    expected.sort(key=lambda x: -x['annual_est'])
    candidates.sort(key=lambda x: x['ex_div_date'], reverse=True)
    return JSONResponse({
        'ok': True, 'source': source,
        'holdings_count': len(holdings),
        'total_annual_est': sum(e['annual_est'] for e in expected),
        'expected': expected,
        'candidates': candidates,
    })


@router.post('/api/dividend/kiwoom/import')
def kiwoom_dividend_import(request: Request, body: dict = Body(default={})):
    """preview 후보 중 선택분을 배당 기록으로 일괄 저장 (중복 스킵)."""
    user = get_login_user(request)
    if not user:
        return login_required_response()
    records = body.get('records') or []
    if not records:
        return JSONResponse({'ok': False, 'error': '가져올 항목이 없습니다.'}, status_code=400)

    inserted, skipped = 0, 0
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for r in records:
                code    = str(r.get('code', '')).strip().zfill(6)[:6]
                ex_date = r.get('ex_div_date')
                if not code.isdigit() or not ex_date:
                    skipped += 1
                    continue
                cur.execute(
                    "SELECT id FROM dividend_records WHERE user_no=%s AND stock_code=%s AND ex_div_date=%s",
                    (user['user_no'], code, ex_date)
                )
                if cur.fetchone():
                    skipped += 1
                    continue
                cur.execute("""
                    INSERT INTO dividend_records
                        (user_no, stock_code, stock_name, ex_div_date, pay_date,
                         dividend_per_share, quantity, total_amount, memo)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    user['user_no'], code, r.get('name', ''),
                    ex_date, r.get('pay_date_est') or None,
                    r.get('dividend_per_share') or 0,
                    r.get('quantity') or 0,
                    r.get('total_amount') or 0,
                    '키움 연동 자동기록',
                ))
                inserted += 1
        conn.commit()
        return JSONResponse({'ok': True, 'inserted': inserted, 'skipped': skipped})
    except Exception as e:
        conn.rollback()
        logger.error(f"[dividend/kiwoom/import] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.get('/api/dividend/calendar')
def dividend_calendar(request: Request):
    """월별 배당 현금흐름: 과거 6개월 실수령 + 향후 6개월 예상.
    예상 = 보유종목의 작년 배당 패턴을 1년 뒤로 투영 (지급월 = 배당락 + 1개월)."""
    user = get_login_user(request)
    if not user:
        return login_required_response()

    from datetime import datetime, timedelta
    now = datetime.now()

    def _ym_shift(base, months: int) -> str:
        y, m = base.year, base.month + months
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        return f"{y:04d}-{m:02d}"

    window = [_ym_shift(now, d) for d in range(-5, 7)]  # 과거5 ~ 미래6 = 12개월
    months = {ym: {'ym': ym, 'received': 0, 'expected': 0} for ym in window}

    # 실수령 (pay_date 기준)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DATE_FORMAT(pay_date,'%%Y-%%m') AS ym, SUM(total_amount) AS total "
                "FROM dividend_records WHERE user_no=%s AND pay_date IS NOT NULL "
                "GROUP BY ym", (user['user_no'],))
            for r in cur.fetchall():
                if r['ym'] in months:
                    months[r['ym']]['received'] = int(r['total'] or 0)
    finally:
        conn.close()

    # 예상 (보유종목 × 과거 1년 배당 패턴 +1년 투영)
    holdings, _src = _get_holdings_for(user['user_no'])
    for h in holdings:
        for dt, amt in _fetch_div_history(h['code']):
            if dt < now - timedelta(days=365):
                continue
            proj_pay = dt + timedelta(days=365 + 30)   # 내년 같은 시기 + 지급 1개월
            if proj_pay < now:
                continue
            ym = proj_pay.strftime('%Y-%m')
            if ym in months:
                months[ym]['expected'] += round(amt * h['quantity'])

    rows = [months[ym] for ym in window]
    return JSONResponse({
        'ok': True, 'months': rows,
        'total_received': sum(r['received'] for r in rows),
        'total_expected': sum(r['expected'] for r in rows),
    })


@router.get('/api/dividend/summary')
def dividend_summary(request: Request):
    user = get_login_user(request)
    if not user:
        return login_required_response()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT YEAR(pay_date) AS yr, SUM(total_amount) AS total, COUNT(*) AS cnt
                FROM dividend_records WHERE user_no=%s AND pay_date IS NOT NULL
                GROUP BY yr ORDER BY yr DESC
            """, (user['user_no'],))
            rows = _serialize_rows(cur.fetchall())
        return JSONResponse({'ok': True, 'by_year': rows})
    except Exception as e:
        logger.error(f"[dividend/summary] {e}", exc_info=True)
        return JSONResponse({'ok': False, 'error': '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()
