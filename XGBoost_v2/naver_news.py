"""
naver_news.py — 네이버 뉴스 검색 + 감성 분석 (규칙 기반 + Claude API).

무료 한도: 25,000 requests/day.
캐시: data/cache/news/{ticker}.json (6시간)

감성 분석:
  - 규칙 기반: 긍정/부정 키워드 사전 매칭 (정확도 약 70%)
"""
import os, re, json, logging, html
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

import requests

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
CACHE_DIR = ROOT / 'data' / 'cache' / 'news'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NAVER_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
CACHE_HOURS  = 6

# ═════════════════════════════════════════════════════════════════════════
# 감성 사전
# ═════════════════════════════════════════════════════════════════════════
POSITIVE_WORDS = {
    "급등": 3, "상승": 2, "호조": 2, "호실적": 3, "흑자": 2,
    "증가": 1, "돌파": 2, "신고가": 3, "강세": 2, "개선": 2,
    "상향": 2, "회복": 2, "성장": 2, "최대": 2, "최고": 2,
    "수주": 2, "계약": 1, "특허": 1, "승인": 2, "통과": 1,
    "호재": 3, "기대": 1, "전망": 1, "목표가": 1, "매수": 2,
    "상한가": 3, "급성장": 3, "대박": 2, "인기": 1, "확대": 1,
    "랠리": 2, "반등": 2, "유지": 0, "추천": 2,
}

NEGATIVE_WORDS = {
    "급락": -3, "하락": -2, "부진": -2, "적자": -3, "손실": -2,
    "감소": -1, "신저가": -3, "약세": -2, "악화": -2, "하향": -2,
    "침체": -2, "우려": -2, "위험": -2, "폭락": -3, "붕괴": -3,
    "악재": -3, "충격": -2, "매도": -2, "하한가": -3, "부도": -3,
    "소송": -2, "제재": -2, "과징금": -2, "리콜": -2, "결함": -2,
    "감산": -2, "축소": -1, "조정": -1, "하회": -2, "실망": -2,
    "주의": -1, "관리종목": -3, "상폐": -3, "횡령": -3, "배임": -3,
}


def _cache_path(code: str) -> Path:
    return CACHE_DIR / f"{code}.json"


def _load_cache(code: str):
    p = _cache_path(code)
    if not p.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    if age.total_seconds() > CACHE_HOURS * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def _save_cache(code: str, data):
    try:
        _cache_path(code).write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _clean_html(text: str) -> str:
    """네이버 API 결과의 HTML 태그 제거."""
    text = re.sub(r'<[^>]+>', '', text or '')
    text = html.unescape(text)
    return text.strip()


# ═════════════════════════════════════════════════════════════════════════
# 뉴스 검색
# ═════════════════════════════════════════════════════════════════════════

def search_news(query: str, display: int = 10) -> list[dict]:
    """
    네이버 뉴스 검색.
    반환: [{title, description, pubDate, link}]
    """
    if not NAVER_ID or not NAVER_SECRET:
        logger.warning("[naver] API 키 없음")
        return []

    headers = {
        "X-Naver-Client-Id":     NAVER_ID,
        "X-Naver-Client-Secret": NAVER_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}

    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers, params=params, timeout=5,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        return [
            {
                "title":       _clean_html(it.get("title", "")),
                "description": _clean_html(it.get("description", "")),
                "pubDate":     it.get("pubDate", ""),
                "link":        it.get("link", ""),
            }
            for it in items
        ]
    except Exception as e:
        logger.debug(f"[naver] {query}: {e}")
        return []


# ═════════════════════════════════════════════════════════════════════════
# 감성 분석 (규칙 기반)
# ═════════════════════════════════════════════════════════════════════════

def get_claude_sentiment(items: list) -> float:
    """뉴스 감성 점수(-1~1). 과금 제거판에서는 LLM 감성분석을 비활성화하고 0.0 반환."""
    return 0.0


def score_text(text: str) -> float:
    """
    텍스트 감성 점수 (-10 ~ +10).
    긍정 키워드 가중치 합산.
    """
    if not text:
        return 0.0
    score = 0
    for word, w in POSITIVE_WORDS.items():
        score += text.count(word) * w
    for word, w in NEGATIVE_WORDS.items():
        score += text.count(word) * w
    return max(-10, min(10, score))


def get_news_features(code: str, name: str) -> dict:
    """
    종목별 뉴스 감성 피처.

    반환:
      n_news_7d       : 최근 7일 뉴스 건수
      sentiment_mean  : 평균 감성 점수
      sentiment_pos   : 긍정 뉴스 비율
      sentiment_neg   : 부정 뉴스 비율
      latest_sent     : 가장 최근 뉴스 점수 (가중치)
    """
    cached = _load_cache(code)
    if cached is not None and "claude_sent" in cached:
        return cached

    # 종목명 + "주가" 조합으로 검색 (노이즈 감소)
    query = f"{name} 주가"
    items = search_news(query, display=20)

    _empty = {
        "n_news_7d":      0,
        "sentiment_mean": 0.0,
        "sentiment_pos":  0.0,
        "sentiment_neg":  0.0,
        "latest_sent":    0.0,
        "claude_sent":    0.0,
    }

    if not items:
        _save_cache(code, _empty)
        return _empty

    # 7일 이내 뉴스만
    cutoff = datetime.now() - timedelta(days=7)
    recent = []
    for it in items:
        try:
            pub = datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %z")
            if pub.replace(tzinfo=None) >= cutoff:
                recent.append(it)
        except Exception:
            recent.append(it)

    if not recent:
        _save_cache(code, _empty)
        return _empty

    scores = [score_text(it["title"] + " " + it["description"]) for it in recent]

    n = len(scores)
    pos = sum(1 for s in scores if s > 0)
    neg = sum(1 for s in scores if s < 0)

    result = {
        "n_news_7d":      n,
        "sentiment_mean": round(float(sum(scores) / n), 4),
        "sentiment_pos":  round(pos / n, 4),
        "sentiment_neg":  round(neg / n, 4),
        "latest_sent":    round(float(scores[0]), 4) if scores else 0.0,
        "claude_sent":    get_claude_sentiment(recent),
    }
    _save_cache(code, result)
    return result


NEWS_COLS = [
    "n_news_7d", "sentiment_mean",
    "sentiment_pos", "sentiment_neg", "latest_sent",
    "claude_sent",
]


if __name__ == '__main__':
    print(get_news_features("005930", "삼성전자"))
    print(get_news_features("000660", "SK하이닉스"))