"""
routes/pipeline.py — 기업 비즈니스 파이프라인 분석
종목코드로 해당 기업의 매입처(원자재/공급망) · 제품 · 매출처(고객군) 분석
DART 기업정보 + Naver Finance + Ollama LLM 기반 구조화
"""
import json
import time
import logging

import requests as _req
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from routes.utils import api_require_login
from routes.company_research import _get_corp_map, _fetch_dart_company

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_table():
    pass  # 구 CRM 테이블 불필요 — app.py 호환용 stub

_CACHE: dict = {}
_CACHE_TTL = 3600  # 1시간

_HEADERS = {'User-Agent': 'Mozilla/5.0'}

SYSTEM_PROMPT = (
    "당신은 한국 주식시장 전문 애널리스트입니다. "
    "주어진 기업의 비즈니스 파이프라인을 분석하여 정확히 JSON 형식으로만 응답하세요. "
    "마크다운 코드 블록(```)이나 추가 설명 없이 순수 JSON만 출력하세요."
)


def _build_prompt(name: str, industry: str) -> str:
    return (
        f"기업명: {name}\n"
        f"업종/분야: {industry}\n\n"
        "위 한국 기업에 대해 알고 있는 정보를 최대한 상세히 활용하여 아래 JSON 형식으로만 응답하세요.\n"
        "{\n"
        '  "business_summary": "핵심 사업 2~3문장 상세 설명",\n'
        '  "competitive_advantage": "핵심 경쟁 우위 2문장",\n'
        '  "value_chain_position": "upstream|midstream|downstream|platform 중 하나",\n'
        '  "founded_context": "설립 배경·역사 한 문장 (모르면 빈 문자열)",\n'
        '  "suppliers": [\n'
        '    {"name": "구체적인 원자재·부품·서비스명", "category": "원자재|부품|에너지|서비스|인력", "importance": "높음|중간", "detail": "이 투입재가 왜 중요한지 한 문장", "substitutability": "낮음|중간|높음"}\n'
        '  ],\n'
        '  "products": [\n'
        '    {"name": "제품·서비스명", "category": "제품|서비스|솔루션", "description": "20자 이내 설명", "revenue_share": 매출비중_정수_퍼센트_추정치, "is_main": true또는false, "growth": "성장|유지|감소"}\n'
        '  ],\n'
        '  "customers": [\n'
        '    {"segment": "고객군명", "type": "B2B|B2C|B2G", "description": "구체적인 주요 고객사 또는 고객층 설명", "revenue_contribution": "높음|중간|낮음", "region": "국내|해외|글로벌"}\n'
        '  ],\n'
        '  "competitors": [\n'
        '    {"name": "경쟁사명", "country": "한국|미국|일본|중국 등", "threat_level": "높음|중간|낮음", "note": "경쟁 포인트 한 문장"}\n'
        '  ],\n'
        '  "geographies": [\n'
        '    {"region": "지역명", "share": 매출비중_정수_퍼센트_추정치, "note": "해당 지역 특이사항"}\n'
        '  ],\n'
        '  "risks": [\n'
        '    {"type": "공급망|시장|규제|기술|환율 중 하나", "title": "리스크 제목", "description": "구체적 리스크 내용 한 문장"}\n'
        '  ],\n'
        '  "partnerships": [\n'
        '    {"partner": "파트너사명", "type": "기술협력|합작투자|납품계약|유통|전략적제휴 중 하나", "note": "협력 내용 한 문장"}\n'
        '  ]\n'
        "}\n"
        "suppliers 최대 6개, products 최대 7개(revenue_share 합계 100에 가깝게), customers 최대 5개, "
        "competitors 최대 5개, geographies 최대 5개(share 합계 100), risks 최대 5개, partnerships 최대 4개.\n"
        "모르는 항목은 빈 배열 []로 두고, 아는 정보는 최대한 구체적으로 작성하세요."
    )


def _fetch_naver_industry(code: str) -> str:
    """Naver Finance에서 업종 설명 조회."""
    try:
        r = _req.get(
            f'https://m.stock.naver.com/api/stock/{code}/integration',
            headers=_HEADERS, timeout=6,
        )
        for t in r.json().get('totalInfos') or []:
            if t.get('code') in ('SECTOR', 'INDUSTRY', 'indutyCode'):
                return t.get('value') or ''
    except Exception:
        pass
    return ''


@router.get('/api/pipeline/company', dependencies=[Depends(api_require_login)])
def company_pipeline(request: Request):
    code = request.query_params.get('code', '').strip().zfill(6)
    if not code or not code.isdigit():
        return JSONResponse({'error': '종목코드를 입력하세요.'}, status_code=400)

    cache_key = f'pipeline_{code}'
    entry = _CACHE.get(cache_key)
    if entry and time.time() - entry['ts'] < _CACHE_TTL:
        return entry['data']

    # DART corp_code 조회
    try:
        corp_map  = _get_corp_map()
        corp_code = corp_map.get(code)
    except Exception as e:
        return JSONResponse({'error': f'DART 조회 실패: {e}'}, status_code=502)

    if not corp_code:
        return JSONResponse({'error': '해당 종목을 DART에서 찾을 수 없습니다.'}, status_code=404)

    # DART 기업 기본정보
    try:
        dart = _fetch_dart_company(corp_code)
    except Exception as e:
        logger.warning(f'[pipeline] DART 기업정보 실패 ({code}): {e}')
        dart = {}

    name      = dart.get('corp_name') or code
    industry  = dart.get('induty_code') or ''
    home_url  = dart.get('hm_url') or ''

    # Naver에서 업종 보완
    if not industry:
        industry = _fetch_naver_industry(code)

    # Ollama 가용성 확인
    try:
        from agent.llm_client import generate, is_available
        if not is_available():
            return JSONResponse(
                {'error': 'Ollama가 실행 중이지 않습니다. localhost:11434 서버를 먼저 시작하세요.'},
                status_code=503,
            )
    except ImportError as e:
        return JSONResponse({'error': f'LLM 모듈 로드 실패: {e}'}, status_code=500)

    # Ollama LLM 분석
    raw = ''
    try:
        raw = generate(
            _build_prompt(name, industry),
            system=SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=4096,
        )

        if not raw.strip():
            return JSONResponse(
                {'error': 'LLM이 빈 응답을 반환했습니다. 모델이 로드됐는지 확인하세요.'},
                status_code=502,
            )

        # 코드블록 / 앞뒤 텍스트 제거 후 JSON 추출
        cleaned = raw.strip()
        # ```json ... ``` 형태
        if '```' in cleaned:
            parts = cleaned.split('```')
            for part in parts:
                part = part.strip()
                if part.startswith('json'):
                    part = part[4:].strip()
                if part.startswith('{'):
                    cleaned = part
                    break
        # 첫 번째 { ... } 블록 추출
        start = cleaned.find('{')
        end   = cleaned.rfind('}')
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]

        pipeline_data = json.loads(cleaned)

    except json.JSONDecodeError as e:
        logger.error(f'[pipeline] JSON 파싱 실패 ({code}): {e}\nraw={raw[:500]}')
        return JSONResponse(
            {'error': f'LLM 응답을 파싱할 수 없습니다: {e}\n응답 미리보기: {raw[:200]}'},
            status_code=502,
        )
    except Exception as e:
        logger.error(f'[pipeline] LLM 호출 실패 ({code}): {e}')
        return JSONResponse({'error': f'LLM 분석 실패: {e}'}, status_code=500)

    result = {
        'ok':          True,
        'code':        code,
        'name':        name,
        'industry':    industry,
        'home_url':    home_url,
        'pipeline':    pipeline_data,
        'analyzed_at': time.strftime('%Y-%m-%d %H:%M'),
    }
    _CACHE[cache_key] = {'ts': time.time(), 'data': result}
    return result


def _empty_pipeline(name: str) -> dict:
    return {
        'business_summary':     f'{name} 분석 정보를 불러올 수 없습니다.',
        'competitive_advantage': '',
        'value_chain_position':  '',
        'suppliers':  [],
        'products':   [],
        'customers':  [],
    }
