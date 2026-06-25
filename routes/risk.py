"""routes/risk.py — 포트폴리오 리스크 대시보드 API.

보유종목 6개월 일봉으로 계산:
  - 종목별: 비중, 연환산 변동성, KOSPI 베타, 최대낙폭(MDD)
  - 포트폴리오: 가중 베타, 변동성, 종목 간 상관관계 행렬
  - 집중도: 종목 비중 상위, HHI, 업종(네이버) 분포
"""
import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from routes.utils import require_login_smart, get_user_no

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_PRICE_CACHE: dict = {}      # code → {'ts', 'series': pd.Series}
_PRICE_TTL = 3600
_SECTOR_CACHE: dict = {}     # code → 업종명 (영구 — 잘 안 바뀜)


def _fetch_closes(ticker_row: dict):
    """(code, 6개월 종가 Series | None)"""
    import yfinance as yf
    code = ticker_row['code']
    cached = _PRICE_CACHE.get(code)
    if cached and _time.time() - cached['ts'] < _PRICE_TTL:
        return code, cached['series']
    series = None
    tickers = [ticker_row.get('ticker')] if ticker_row.get('ticker') else []
    tickers += [code + '.KS', code + '.KQ']
    for t in tickers:
        if not t:
            continue
        try:
            h = yf.Ticker(t).history(period='6mo')
            if h is not None and len(h) > 30:
                series = h['Close'].dropna()
                break
        except Exception:
            continue
    _PRICE_CACHE[code] = {'ts': _time.time(), 'series': series}
    return code, series


def _fetch_sector(code: str) -> str:
    """네이버 금융 종목 페이지에서 업종명 파싱 (영구 캐시)."""
    if code in _SECTOR_CACHE:
        return _SECTOR_CACHE[code]
    sector = '기타'
    try:
        import re
        import urllib.request
        req = urllib.request.Request(
            f'https://finance.naver.com/item/main.naver?code={code}',
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124',
                     'Referer': 'https://finance.naver.com/'})
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode('utf-8', errors='replace')
        m = re.search(r'sise_group_detail\.naver\?type=upjong[^"]*">([^<]+)</a>', html)
        if m:
            sector = m.group(1).strip()
    except Exception as e:
        logger.debug(f'[risk] {code} 업종 조회 실패: {e}')
    _SECTOR_CACHE[code] = sector
    return sector


@router.get('/api/risk/dashboard')
def risk_dashboard(request: Request):
    import numpy as np
    import pandas as pd

    user_no = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT h.code, h.name, h.quantity, h.avg_price, k.ticker
                FROM stock_holdings h
                LEFT JOIN kr_stocks k ON k.code = h.code
                WHERE h.member_id = %s AND h.quantity > 0
            """, (user_no,))
            holdings = cur.fetchall()
    finally:
        conn.close()

    if not holdings:
        return JSONResponse({'ok': False,
                             'error': '보유종목이 없습니다. 포트폴리오에서 키움 동기화를 먼저 실행하세요.'},
                            status_code=404)

    # ── 가격 시계열 (병렬) + KOSPI ──
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = dict(ex.map(_fetch_closes, holdings))
        kospi_future = ex.submit(_fetch_closes, {'code': '^KS11', 'ticker': '^KS11'})
    _, kospi = kospi_future.result()
    kospi_ret = kospi.pct_change().dropna() if kospi is not None else None

    # ── 종목별 지표 ──
    items, ret_map = [], {}
    for h in holdings:
        code = h['code']
        series = results.get(code)
        last_price = float(series.iloc[-1]) if series is not None else h['avg_price']
        eval_amt = round(last_price * h['quantity'])

        vol = beta = mdd = None
        if series is not None and len(series) > 30:
            rets = series.pct_change().dropna()
            ret_map[code] = rets
            vol = round(float(rets.std()) * (252 ** 0.5) * 100, 1)   # 연환산 변동성 %
            peak = series.cummax()
            mdd = round(float(((series - peak) / peak).min()) * 100, 1)
            if kospi_ret is not None:
                aligned = pd.concat([rets, kospi_ret], axis=1, join='inner').dropna()
                if len(aligned) > 30 and float(aligned.iloc[:, 1].var()) > 0:
                    beta = round(float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
                                       / aligned.iloc[:, 1].var()), 2)

        items.append({
            'code': code, 'name': h['name'], 'quantity': h['quantity'],
            'eval_amount': eval_amt, 'volatility': vol, 'beta': beta, 'mdd': mdd,
        })

    total_eval = sum(i['eval_amount'] for i in items) or 1
    for i in items:
        i['weight'] = round(i['eval_amount'] / total_eval * 100, 1)
    items.sort(key=lambda x: -x['weight'])

    # ── 포트폴리오 지표 ──
    w = {i['code']: i['eval_amount'] / total_eval for i in items}
    port_beta = round(sum(w[i['code']] * i['beta'] for i in items if i['beta'] is not None), 2) \
        if any(i['beta'] is not None for i in items) else None

    port_vol = None
    if ret_map:
        df = pd.DataFrame(ret_map).dropna()
        if len(df) > 30:
            weights = np.array([w.get(c, 0) for c in df.columns])
            port_rets = (df * weights).sum(axis=1)
            port_vol = round(float(port_rets.std()) * (252 ** 0.5) * 100, 1)

    # ── 상관관계 행렬 ──
    corr = None
    if len(ret_map) >= 2:
        cdf = pd.DataFrame(ret_map).dropna()
        if len(cdf) > 30:
            cm = cdf.corr().round(2)
            name_of = {i['code']: i['name'] for i in items}
            corr = {'labels': [name_of.get(c, c) for c in cm.columns],
                    'matrix': cm.values.tolist()}

    # ── 집중도 ──
    hhi = round(sum((i['weight'] / 100) ** 2 for i in items) * 10000)  # 0~10000
    with ThreadPoolExecutor(max_workers=6) as ex:
        sectors = dict(zip([i['code'] for i in items],
                           ex.map(_fetch_sector, [i['code'] for i in items])))
    sector_agg: dict = {}
    for i in items:
        s = sectors.get(i['code']) or '기타'
        sector_agg[s] = sector_agg.get(s, 0) + i['weight']
    sector_dist = sorted(
        [{'sector': k, 'weight': round(v, 1)} for k, v in sector_agg.items()],
        key=lambda x: -x['weight'])

    warnings = []
    if items and items[0]['weight'] > 40:
        warnings.append(f"단일 종목 집중: {items[0]['name']} {items[0]['weight']}%")
    if sector_dist and sector_dist[0]['weight'] > 60:
        warnings.append(f"업종 집중: {sector_dist[0]['sector']} {sector_dist[0]['weight']}%")
    if port_beta is not None and port_beta > 1.3:
        warnings.append(f"고베타 포트폴리오 (β={port_beta}) — 시장 하락 시 손실 확대")

    return {
        'ok': True,
        'total_eval': total_eval,
        'portfolio': {'beta': port_beta, 'volatility': port_vol, 'hhi': hhi},
        'items': items,
        'correlation': corr,
        'sectors': sector_dist,
        'warnings': warnings,
    }
