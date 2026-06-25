import io
import os
import time
import zipfile
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from routes.utils import require_login, api_require_login
from templates_config import render

router = APIRouter()

DART_KEY = os.getenv('DART_API_KEY')
_HEADERS  = {'User-Agent': 'Mozilla/5.0'}

# ── corp_code 매핑 캐시 (stock_code 6자리 → corp_code 8자리) ──
_corp_map    = {}
_corp_map_ts = 0.0
_CORP_TTL    = 86400  # 24시간


def _get_corp_map():
    global _corp_map, _corp_map_ts
    if _corp_map and time.time() - _corp_map_ts < _CORP_TTL:
        return _corp_map
    r = requests.get(
        'https://opendart.fss.or.kr/api/corpCode.xml',
        params={'crtfc_key': DART_KEY},
        timeout=20,
    )
    r.raise_for_status()
    z    = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read('CORPCODE.xml').decode('utf-8'))
    m = {}
    for item in root.findall('list'):
        sc = (item.findtext('stock_code') or '').strip()
        cc = (item.findtext('corp_code')  or '').strip()
        if sc and cc:
            m[sc] = cc
    _corp_map    = m
    _corp_map_ts = time.time()
    return m


# ── 일반 응답 캐시 ──
_cache    = {}
_CACHE_TTL = 3600  # 1시간


def _cached(key, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry['ts'] < _CACHE_TTL:
        return entry['data']
    data = fn()
    _cache[key] = {'ts': time.time(), 'data': data}
    return data


# ── Naver Finance ──
def _fetch_naver(code):
    """basic(현재가/등락) + integration(PER·PBR 등 지표) 병합"""
    basic = requests.get(
        f'https://m.stock.naver.com/api/stock/{code}/basic',
        headers=_HEADERS, timeout=6,
    ).json()

    intg = requests.get(
        f'https://m.stock.naver.com/api/stock/{code}/integration',
        headers=_HEADERS, timeout=6,
    ).json()

    info_map = {}
    for t in (intg.get('totalInfos') or []):
        c = t.get('code')
        if c:
            info_map[c] = t.get('value') or ''

    return {
        'stockName':                    basic.get('stockName', ''),
        'closePrice':                   basic.get('closePrice', ''),
        'compareToPreviousClosePrice':  basic.get('compareToPreviousClosePrice', ''),
        'fluctuationsRatio':            basic.get('fluctuationsRatio', ''),
        'infoMap':                      info_map,
    }


# ── DART 기업개황 ──
def _fetch_dart_company(corp_code):
    r = requests.get(
        'https://opendart.fss.or.kr/api/company.json',
        params={'crtfc_key': DART_KEY, 'corp_code': corp_code},
        timeout=8,
    )
    r.raise_for_status()
    data = r.json()
    if data.get('status') != '000':
        raise ValueError(data.get('message', 'DART 기업정보 조회 실패'))
    return data


# ── DART 재무제표 ──
_REVENUE = {'매출액', '수익(매출액)', '영업수익', '매출'}
_OPER    = {'영업이익', '영업이익(손실)', '영업손익'}
_NET     = {'당기순이익', '당기순이익(손실)', '당기순손익', '분기순이익'}


def _extract_key_accounts(items):
    r = {}
    for item in items:
        nm = (item.get('account_nm') or '').strip()
        if nm in _REVENUE and 'revenue'           not in r: r['revenue']           = item
        elif nm in _OPER   and 'oper_income'      not in r: r['oper_income']       = item
        elif nm in _NET    and 'net_income'        not in r: r['net_income']        = item
        elif nm == '자산총계':                                 r['total_assets']      = item
        elif nm == '부채총계':                                 r['total_liabilities'] = item
        elif nm == '자본총계':                                 r['total_equity']      = item
    return r


def _fetch_financials(corp_code):
    for fs_div in ('CFS', 'OFS'):
        for year in ('2024', '2023', '2022'):
            r = requests.get(
                'https://opendart.fss.or.kr/api/fnlttSinglAcnt.json',
                params={
                    'crtfc_key':  DART_KEY,
                    'corp_code':  corp_code,
                    'bsns_year':  year,
                    'reprt_code': '11011',
                    'fs_div':     fs_div,
                },
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            if data.get('status') == '000' and data.get('list'):
                return {
                    'year':    year,
                    'fs_div':  fs_div,
                    'summary': _extract_key_accounts(data['list']),
                }
    return {'year': None, 'fs_div': None, 'summary': {}}


# ── 라우트 ──
# '/company_research' 페이지는 React SPA(client/src/pages/CompanyResearch.jsx)가
# app.py 의 SPA catch-all 을 통해 직접 렌더링한다. 레거시 서버 템플릿 라우트는 제거됨.
@router.get('/api/company_research', dependencies=[Depends(api_require_login)])
def get_company_research(request: Request):
    code = request.query_params.get('code', '').strip().zfill(6)
    if not code or not code.isdigit():
        return JSONResponse({'error': '유효한 종목코드를 입력해주세요.'}, status_code=400)

    # 1. corp_code 조회
    try:
        corp_map  = _get_corp_map()
        corp_code = corp_map.get(code)
    except Exception as e:
        return JSONResponse({'error': f'DART 코드 매핑 로드 실패: {e}'}, status_code=502)

    if not corp_code:
        return JSONResponse({'error': f'종목코드 {code}를 DART에서 찾을 수 없습니다.'}, status_code=404)

    # 2. 기업정보 · 주가 · 재무 병렬 조회
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_co  = ex.submit(lambda: _cached(f'dart_co_{corp_code}',  lambda: _fetch_dart_company(corp_code)))
        f_st  = ex.submit(lambda: _cached(f'naver_{code}',         lambda: _fetch_naver(code)))
        f_fin = ex.submit(lambda: _cached(f'dart_fin_{corp_code}', lambda: _fetch_financials(corp_code)))

        company    = f_co.result()  if not f_co.exception()  else {'error': str(f_co.exception())}
        stock      = f_st.result()  if not f_st.exception()  else {'error': str(f_st.exception())}
        financials = f_fin.result() if not f_fin.exception() else {'error': str(f_fin.exception())}

    return {'company': company, 'stock': stock, 'financials': financials}
