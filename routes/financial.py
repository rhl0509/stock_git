# -*- coding: utf-8 -*-
import logging
import json
import os
import re
import time
import urllib.request
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse, Response
import pandas as pd

from korea_stock_data import FnGuideSource
from templates_config import render

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_fnguide   = FnGuideSource()
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'cache', 'financial')
_NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
    'Referer':    'https://m.stock.naver.com/',
}


# ── 파일 캐시 ──
def _load_cache(key: str, ttl_hours: float = 12):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f'{key}.json')
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > ttl_hours * 3600:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(key: str, data) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(os.path.join(_CACHE_DIR, f'{key}.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


# ── DataFrame → JSON-safe list ──
def _df_to_records(df) -> list:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [' '.join(str(c) for c in col).strip() for col in out.columns]
    out.columns = [str(c) for c in out.columns]

    cols        = list(out.columns)
    label_col   = next((c for c in cols if 'IFRS' in c), None)
    period_cols = [c for c in cols if re.match(r'^\d{4}/\d{2}', c)]

    if label_col and period_cols:
        out = out[[label_col] + period_cols].copy()
        out.columns = ['항목'] + period_cols
    else:
        out = out.reset_index()
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                out[col] = out[col].dt.strftime('%Y-%m-%d')

    return json.loads(out.to_json(orient='records', force_ascii=False))


# ── 페이지 ──
@router.get('/financial')
def financial_page(request: Request):
    return render(request, 'stock/financial_analysis.html')


# ── 현재가 프록시 ──
@router.get('/financial/price/{code}')
def financial_price(code: str):
    if not re.match(r'^\d{6}$', code):
        return JSONResponse({'error': '숫자 6자리 코드만 지원합니다'}, status_code=400)
    try:
        req = urllib.request.Request(
            f'https://m.stock.naver.com/api/stock/{code}/basic',
            headers=_NAVER_HEADERS
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            return Response(content=r.read(), media_type='application/json; charset=utf-8')
    except Exception as e:
        logger.error(f'[financial] {e}', exc_info=True)
        return JSONResponse({'error': '서버 오류가 발생했습니다.'}, status_code=500)


# ── React SPA용 실적 요약 API ────────────────────────────────────────────────
# Financial.jsx가 사용. 네이버 finance API의 연간/분기 테이블 + 기본 지표 + EPS 차트.

def _parse_naver_num(s):
    """'971,467' → 971467, '12.34' → 12.34, '-'/''/None → None"""
    if s is None:
        return None
    s = str(s).replace(',', '').strip()
    if not s or s == '-':
        return None
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return None


def _fmt_market_cap(mcap_million: int) -> str | None:
    """백만원 단위 시총 → '423조 1,234억' 문자열"""
    if not mcap_million:
        return None
    total = mcap_million * 1_000_000
    jo, eok = divmod(total, 1_000_000_000_000)
    eok //= 100_000_000
    if jo:
        return f'{jo:,}조 {eok:,}억' if eok else f'{jo:,}조'
    return f'{eok:,}억'


def _fetch_naver_finance_table(code: str, kind: str) -> dict:
    """kind: 'annual' | 'quarter' → {'headers': [...], 'rows': [...], 'eps': {...}}"""
    req = urllib.request.Request(
        f'https://m.stock.naver.com/api/stock/{code}/finance/{kind}',
        headers=_NAVER_HEADERS
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode('utf-8'))
    fi = d.get('financeInfo') or {}
    titles = fi.get('trTitleList') or []
    keys   = [t.get('key') for t in titles]
    headers = [{'title': t.get('title', '').rstrip('.'),
                'isConsensus': t.get('isConsensus') == 'Y'} for t in titles]
    rows, eps_values = [], None
    for row in fi.get('rowList') or []:
        cols   = row.get('columns') or {}
        values = [_parse_naver_num((cols.get(k) or {}).get('value')) for k in keys]
        rows.append({'label': row.get('title', ''), 'values': values})
        if row.get('title') == 'EPS':
            eps_values = values
    eps_chart = None
    if eps_values and any(v is not None for v in eps_values):
        eps_chart = {'headers': [h['title'] for h in headers], 'values': eps_values}
    return {'headers': headers, 'rows': rows, 'epsChart': eps_chart}


@router.get('/api/financial/{code}')
def api_financial_summary(code: str):
    code = code.strip().zfill(6)
    if not re.match(r'^\d{6}$', code):
        return JSONResponse({'ok': False, 'error': '숫자 6자리 코드만 지원합니다'}, status_code=400)

    cache_key = f'api_{code}_{datetime.now().strftime("%Y%m%d")}'
    cached = _load_cache(cache_key, ttl_hours=12)
    if cached:
        return cached

    # 기본 지표 (현재가/PER/PBR/52주/시총 등) — kiwoom 모듈의 네이버 통합 조회 재사용
    from routes.kiwoom import _fetch_naver_full
    base = _fetch_naver_full(code)
    if base is None:
        return JSONResponse({'ok': False, 'error': '종목 정보를 가져오지 못했습니다.'}, status_code=502)

    result = {
        'ok': True, 'code': code, 'name': base.get('name', code),
        'price': base.get('price', 0),
        'market_cap': _fmt_market_cap(base.get('market_cap', 0)),
        'per': base.get('per'), 'pbr': base.get('pbr'),
        'eps': base.get('eps'), 'bps': base.get('bps'),
        'dividend': base.get('dividend'),
        'foreign_ratio': base.get('foreign_ratio'),
        'week52_high': base.get('week52_high'), 'week52_low': base.get('week52_low'),
        'est_per': None, 'est_eps': None,
        'annual': None, 'quarter': None, 'epsChart': None,
    }

    try:
        annual = _fetch_naver_finance_table(code, 'annual')
        result['annual']   = {'headers': annual['headers'], 'rows': annual['rows']}
        result['epsChart'] = annual['epsChart']
        # 추정 EPS/PER: 연간 테이블의 첫 컨센서스 컬럼에서 계산
        if annual['epsChart']:
            for h, v in zip(annual['headers'], annual['epsChart']['values']):
                if h['isConsensus'] and v:
                    result['est_eps'] = v
                    if result['price'] and v > 0:
                        result['est_per'] = round(result['price'] / v, 2)
                    break
    except Exception as e:
        logger.warning(f'[financial/api] {code} 연간 실적 조회 실패: {e}')

    try:
        quarter = _fetch_naver_finance_table(code, 'quarter')
        result['quarter'] = {'headers': quarter['headers'], 'rows': quarter['rows']}
    except Exception as e:
        logger.warning(f'[financial/api] {code} 분기 실적 조회 실패: {e}')

    if result['annual'] or result['quarter']:
        _save_cache(cache_key, result)
    return result


@router.get('/api/financial/{code}/chart')
def api_financial_chart(code: str):
    """3년 월봉 종가 (yfinance). Financial.jsx 주가 차트 탭."""
    code = code.strip().zfill(6)
    if not re.match(r'^\d{6}$', code):
        return JSONResponse({'ok': False, 'error': '숫자 6자리 코드만 지원합니다'}, status_code=400)

    cache_key = f'chart_{code}_{datetime.now().strftime("%Y%m%d")}'
    cached = _load_cache(cache_key, ttl_hours=12)
    if cached:
        return cached

    import yfinance as yf
    hist = None
    for suffix in ('.KS', '.KQ'):
        try:
            h = yf.Ticker(code + suffix).history(period='3y', interval='1mo')
            if h is not None and not h.empty:
                hist = h
                break
        except Exception:
            continue
    if hist is None:
        return {'ok': True, 'chart': []}

    chart = [
        {'date': idx.strftime('%Y-%m-%d'), 'close': round(float(close), 2)}
        for idx, close in hist['Close'].dropna().items()
    ]
    result = {'ok': True, 'chart': chart}
    if chart:
        _save_cache(cache_key, result)
    return result


# ── 통합 데이터 API ──
@router.get('/financial/data/{code}')
def financial_data(code: str):
    code = code.strip().zfill(6)
    if not re.match(r'^\d{6}$', code):
        return JSONResponse({
            'ok':    False,
            'error': f'지원하지 않는 종목 코드입니다: {code}\n영문자가 포함된 코드(스팩, 신주인수권 등)는 재무 데이터가 없습니다.',
        }, status_code=400)

    # 캐시 (하루 1회 갱신)
    cache_key = f'{code}_{datetime.now().strftime("%Y%m%d")}'
    cached = _load_cache(cache_key, ttl_hours=12)
    if cached:
        return cached

    # 1) 재무제표
    fin  = _fnguide.financials(code)
    data = {}
    for k, v in fin.items():
        data[k] = _df_to_records(v) if isinstance(v, pd.DataFrame) else []

    # 2) 재무비율
    ratios = [
        _df_to_records(df)
        for df in _fnguide.ratios(code)
        if isinstance(df, pd.DataFrame) and not df.empty
    ]

    # 3) 컨센서스
    try:
        req = urllib.request.Request(
            f'https://m.stock.naver.com/api/stock/{code}/integration',
            headers=_NAVER_HEADERS
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read().decode('utf-8'))
        ci = d.get('consensusInfo') or {}
        consensus = {
            'recommend_mean': ci.get('recommMean'),
            'target_price':   ci.get('priceTargetMean'),
            'create_date':    ci.get('createDate'),
            'researches': [
                {
                    'broker': x.get('bnm', ''),
                    'title':  x.get('tit', ''),
                    'price':  x.get('rcnt', ''),
                    'date':   x.get('wdt', ''),
                }
                for x in (d.get('researches') or [])
            ],
        }
    except Exception:
        consensus = {}

    result = {
        'ok':         True,
        'code':       code,
        'financials': data,
        'ratios':     ratios,
        'consensus':  consensus,
    }
    _save_cache(cache_key, result)
    return result
