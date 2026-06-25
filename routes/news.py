import time
import requests
import xml.etree.ElementTree as ET
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from routes.utils import require_login, api_require_login
from urllib.parse import quote
from templates_config import render

router = APIRouter()

_cache = {}
_CACHE_TTL = 600  # 10분


@router.get('/news', dependencies=[Depends(require_login)])
def news_page(request: Request):
    return render(request, 'stock/news.html')


@router.get('/api/news/search', dependencies=[Depends(api_require_login)])
def search_news(request: Request):
    q = request.query_params.get('q', '').strip()
    if not q:
        return JSONResponse({'error': '검색어를 입력해주세요.'}, status_code=400)

    cached = _cache.get(q)
    if cached and time.time() - cached['ts'] < _CACHE_TTL:
        return cached['data']

    url = f'https://news.google.com/rss/search?q={quote(q)}&hl=ko&gl=KR&ceid=KR:ko'
    try:
        resp = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
    except Exception as e:
        return JSONResponse({'error': '뉴스를 불러오지 못했습니다.'}, status_code=502)

    root = ET.fromstring(resp.content)
    items = []
    for item in root.findall('./channel/item'):
        title = item.findtext('title', '')
        link = item.findtext('link', '')
        pub_date = item.findtext('pubDate', '')
        source_el = item.find('source')
        source = source_el.text if source_el is not None else ''

        if not source and ' - ' in title:
            title, source = title.rsplit(' - ', 1)

        items.append({
            'title': title,
            'link': link,
            'pubDate': pub_date,
            'source': source,
        })

    result = {'items': items, 'total': len(items)}
    _cache[q] = {'ts': time.time(), 'data': result}
    return result
