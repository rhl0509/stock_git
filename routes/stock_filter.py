from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from routes.utils import api_require_login
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

UNIVERSE = [
    {'code': '005930', 'name': '삼성전자'},
    {'code': '000660', 'name': 'SK하이닉스'},
    {'code': '373220', 'name': 'LG에너지솔루션'},
    {'code': '207940', 'name': '삼성바이오로직스'},
    {'code': '005380', 'name': '현대차'},
    {'code': '068270', 'name': '셀트리온'},
    {'code': '000270', 'name': '기아'},
    {'code': '005490', 'name': 'POSCO홀딩스'},
    {'code': '006400', 'name': '삼성SDI'},
    {'code': '051910', 'name': 'LG화학'},
    {'code': '035420', 'name': 'NAVER'},
    {'code': '035720', 'name': '카카오'},
    {'code': '012330', 'name': '현대모비스'},
    {'code': '028260', 'name': '삼성물산'},
    {'code': '105560', 'name': 'KB금융'},
    {'code': '055550', 'name': '신한지주'},
    {'code': '086790', 'name': '하나금융지주'},
    {'code': '066570', 'name': 'LG전자'},
    {'code': '015760', 'name': '한국전력'},
    {'code': '247540', 'name': '에코프로비엠'},
    {'code': '086520', 'name': '에코프로'},
    {'code': '003670', 'name': '포스코퓨처엠'},
    {'code': '096770', 'name': 'SK이노베이션'},
    {'code': '017670', 'name': 'SK텔레콤'},
    {'code': '030200', 'name': 'KT'},
    {'code': '323410', 'name': '카카오뱅크'},
    {'code': '259960', 'name': '크래프톤'},
    {'code': '036570', 'name': '엔씨소프트'},
    {'code': '034020', 'name': '두산에너빌리티'},
    {'code': '012450', 'name': '한화에어로스페이스'},
    {'code': '010130', 'name': '고려아연'},
    {'code': '090430', 'name': '아모레퍼시픽'},
    {'code': '018260', 'name': '삼성에스디에스'},
    {'code': '352820', 'name': '하이브'},
    {'code': '267250', 'name': 'HD현대'},
    {'code': '032830', 'name': '삼성생명'},
    {'code': '047810', 'name': '한국항공우주'},
    {'code': '316140', 'name': '우리금융지주'},
    {'code': '011070', 'name': 'LG이노텍'},
    {'code': '032640', 'name': 'LG유플러스'},

    # ── 추가 60개 (KOSPI 대형주 / 중형주 / KOSDAQ 우량주) ──
    # 금융
    {'code': '139480', 'name': '이마트'},
    {'code': '035250', 'name': '강원랜드'},
    {'code': '000810', 'name': '삼성화재'},
    {'code': '082640', 'name': '동양생명'},
    {'code': '071050', 'name': '한국금융지주'},
    {'code': '003550', 'name': 'LG'},
    {'code': '009540', 'name': 'HD한국조선해양'},
    {'code': '010950', 'name': 'S-Oil'},
    {'code': '096530', 'name': '씨젠'},
    {'code': '068760', 'name': '셀트리온제약'},

    # 반도체·전자
    {'code': '005935', 'name': '삼성전자우'},
    {'code': '042700', 'name': '한미반도체'},
    {'code': '000990', 'name': 'DB하이텍'},
    {'code': '336370', 'name': '솔루스첨단소재'},
    {'code': '357780', 'name': '솔브레인'},
    {'code': '196170', 'name': '알테오젠'},
    {'code': '214150', 'name': '클래시스'},
    {'code': '095340', 'name': 'ISC'},
    {'code': '229640', 'name': 'LS에코에너지'},
    {'code': '009150', 'name': '삼성전기'},

    # 자동차·부품
    {'code': '161390', 'name': '한국타이어앤테크놀로지'},
    {'code': '060980', 'name': 'HL홀딩스'},
    {'code': '004020', 'name': '현대제철'},
    {'code': '241560', 'name': '두산밥캣'},
    {'code': '011200', 'name': 'HMM'},
    {'code': '006800', 'name': '미래에셋증권'},
    {'code': '016360', 'name': '삼성증권'},
    {'code': '039490', 'name': '키움증권'},
    {'code': '003490', 'name': '대한항공'},
    {'code': '020560', 'name': '아시아나항공'},

    # 화학·소재
    {'code': '011790', 'name': 'SKC'},
    {'code': '004490', 'name': '세방전지'},
    {'code': '006360', 'name': 'GS건설'},
    {'code': '000720', 'name': '현대건설'},
    {'code': '047040', 'name': '대우건설'},
    {'code': '010060', 'name': 'OCI홀딩스'},
    {'code': '298000', 'name': '효성화학'},
    {'code': '298050', 'name': 'HS효성첨단소재'},
    {'code': '004000', 'name': '롯데정밀화학'},
    {'code': '025540', 'name': '한국단자'},

    # 바이오·헬스케어
    {'code': '128940', 'name': '한미약품'},
    {'code': '000100', 'name': '유한양행'},
    {'code': '185750', 'name': '종근당'},
    {'code': '002380', 'name': 'KCC'},
    {'code': '271560', 'name': '오리온'},
    {'code': '097950', 'name': 'CJ제일제당'},
    {'code': '004370', 'name': '농심'},
    {'code': '005300', 'name': '롯데칠성'},
    {'code': '280360', 'name': '롯데웰푸드'},
    {'code': '007070', 'name': 'GS리테일'},

    # 유통·소비재
    {'code': '023530', 'name': '롯데쇼핑'},
    {'code': '069960', 'name': '현대백화점'},
    {'code': '004170', 'name': '신세계'},
    {'code': '000240', 'name': '한국앤컴퍼니'},
    {'code': '088350', 'name': '한화생명'},
    {'code': '001450', 'name': '현대해상'},
    {'code': '000670', 'name': '영풍'},
    {'code': '005830', 'name': 'DB손해보험'},
    {'code': '017800', 'name': '현대엘리베이터'},
    {'code': '009830', 'name': '한화솔루션'},
]

KOSDAQ_CODES = {
    '247540', '086520', '042700', '336370', '357780',
    '196170', '214150', '095340', '229640', '096530',
    '025540',
}

def _yf_ticker(code):
    return code + ('.KQ' if code in KOSDAQ_CODES else '.KS')

_cache = {'result': None, 'ts': 0}
CACHE_TTL = 300


def _extract_series(raw_data, ticker_symbol, field):
    import pandas as pd
    cols = raw_data.columns
    if isinstance(cols, pd.MultiIndex):
        level0 = cols.get_level_values(0).unique().tolist()
        level1 = cols.get_level_values(1).unique().tolist()
        if field in level0 and ticker_symbol in level1:
            return raw_data[field][ticker_symbol].dropna()
        if ticker_symbol in level0 and field in level1:
            return raw_data[ticker_symbol][field].dropna()
        raise KeyError(f"'{field}' 또는 '{ticker_symbol}'을 컬럼에서 찾을 수 없습니다.")
    return raw_data[field].dropna()


def _calc_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss + 1e-10)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def _analyze_stock(ticker_symbol, code, name, raw_data):
    try:
        close  = _extract_series(raw_data, ticker_symbol, 'Close')
        volume = _extract_series(raw_data, ticker_symbol, 'Volume')
        if len(close) < 30:
            return None

        current = float(close.iloc[-1])
        ma5     = float(close.rolling(5).mean().iloc[-1])
        ma20    = float(close.rolling(20).mean().iloc[-1])
        ma60    = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else None
        rsi     = _calc_rsi(close)

        ema12  = close.ewm(span=12, adjust=False).mean()
        ema26  = close.ewm(span=26, adjust=False).mean()
        macd   = float((ema12 - ema26).iloc[-1])
        signal = float((ema12 - ema26).ewm(span=9, adjust=False).mean().iloc[-1])

        w52h = float(close.rolling(min(252, len(close))).max().iloc[-1])
        w52l = float(close.rolling(min(252, len(close))).min().iloc[-1])

        vol_avg   = float(volume.rolling(20).mean().iloc[-1])
        vol_now   = float(volume.iloc[-1])
        vol_ratio = round(vol_now / vol_avg, 2) if vol_avg > 0 else 1.0

        ma5_prev  = float(close.rolling(5).mean().iloc[-2])
        ma20_prev = float(close.rolling(20).mean().iloc[-2])
        golden_cross = (ma5_prev < ma20_prev) and (ma5 > ma20)
        dead_cross   = (ma5_prev > ma20_prev) and (ma5 < ma20)

        score = 0
        if rsi < 40:             score += 2
        if rsi < 30:             score += 1
        if current > ma20:       score += 1
        if current > ma5 > ma20: score += 1
        if macd > signal:        score += 2
        if vol_ratio > 1.5:      score += 1
        if golden_cross:         score += 1

        sell_score = 0
        if rsi > 60:             sell_score += 2
        if rsi > 70:             sell_score += 1
        if current < ma20:       sell_score += 1
        if current < ma5 < ma20: sell_score += 1
        if macd < signal:        sell_score += 2
        if dead_cross:           sell_score += 1

        tags = []
        if rsi < 30:               tags.append('RSI과매도')
        if rsi > 70:               tags.append('RSI과매수')
        if golden_cross:           tags.append('골든크로스')
        if dead_cross:             tags.append('데드크로스')
        if vol_ratio >= 1.5:       tags.append('거래량급등')
        if current >= w52h * 0.97: tags.append('52주신고가')
        if current <= w52l * 1.03: tags.append('52주신저가')
        if score >= 4:             tags.append('강력매수')
        if sell_score >= 4:        tags.append('강력매도')

        macd_hist     = round(macd - signal, 2)
        price_vs_ma20 = round((current / ma20 - 1) * 100, 2)

        return {
            'code':           code,
            'name':           name,
            'price':          round(current),
            'rsi':            round(rsi, 1),
            'ma5':            round(ma5),
            'ma20':           round(ma20),
            'ma60':           round(ma60) if ma60 else None,
            'price_vs_ma20':  price_vs_ma20,
            'macd':           round(macd, 2),
            'macd_signal':    round(signal, 2),
            'macd_hist':      macd_hist,
            'vol_ratio':      vol_ratio,
            'week52_high':    round(w52h),
            'week52_low':     round(w52l),
            'near_52w_high':  current >= w52h * 0.97,
            'near_52w_low':   current <= w52l * 1.03,
            'golden_cross':   golden_cross,
            'dead_cross':     dead_cross,
            'score':          score,
            'sell_score':     sell_score,
            'strong_buy':     score >= 4,
            'strong_sell':    sell_score >= 4,
            'tags':           tags,
        }
    except Exception as e:
        logger.error(f"[Filter] {code} 분석 오류: {e}")
        return None


def _run_screen():
    now = time.time()
    if _cache['result'] is not None and now - _cache['ts'] < CACHE_TTL:
        return _cache['result']

    import yfinance as yf
    tickers = [_yf_ticker(s['code']) for s in UNIVERSE]

    try:
        raw = yf.download(tickers, period='6mo', auto_adjust=True, progress=False, threads=True)
    except Exception as e:
        logger.error(f"[Filter] yfinance 다운로드 오류: {e}")
        return []

    if raw is None or raw.empty:
        return []

    logger.info(f"[Filter] 다운로드 완료. 컬럼 구조: {list(raw.columns[:4])}...")

    results = []
    for stock in UNIVERSE:
        ticker = _yf_ticker(stock['code'])
        data = _analyze_stock(ticker, stock['code'], stock['name'], raw)
        if data:
            results.append(data)

    logger.info(f"[Filter] 스크리닝 완료: {len(results)}/{len(UNIVERSE)}개 성공")
    _cache['result'] = results
    _cache['ts']     = now
    return results


@router.post('/stock/screen', dependencies=[Depends(api_require_login)])
def screen_stocks(request: Request, body: dict = Body(default={})):
    f        = body.get('filter',   'all')
    sort_by  = body.get('sort_by',  'score')
    sort_dir = body.get('sort_dir', 'desc')

    results = _run_screen()
    if not results:
        return JSONResponse({"error": "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."}, status_code=500)

    filter_map = {
        'strong_buy':    lambda r: r['strong_buy'],
        'strong_sell':   lambda r: r['strong_sell'],
        'rsi_low':       lambda r: r['rsi'] < 40,
        'rsi_high':      lambda r: r['rsi'] > 60,
        'golden_cross':  lambda r: r['golden_cross'],
        'dead_cross':    lambda r: r['dead_cross'],
        'volume_surge':  lambda r: r['vol_ratio'] >= 1.5,
        'near_52w_high': lambda r: r['near_52w_high'],
        'near_52w_low':  lambda r: r['near_52w_low'],
    }
    fn = filter_map.get(f)
    filtered = [r for r in results if fn(r)] if fn else results

    reverse = (sort_dir == 'desc')
    key_map = {
        'rsi':           lambda r: r['rsi'],
        'score':         lambda r: r['score'],
        'sell_score':    lambda r: r['sell_score'],
        'vol_ratio':     lambda r: r['vol_ratio'],
        'price_vs_ma20': lambda r: r['price_vs_ma20'],
        'macd_hist':     lambda r: r['macd_hist'],
        'price':         lambda r: r['price'],
    }
    filtered.sort(key=key_map.get(sort_by, key_map['score']), reverse=reverse)

    return {"count": len(filtered), "total": len(results), "results": filtered}


@router.get('/stock/investor', dependencies=[Depends(api_require_login)])
def investor_flow(request: Request):
    inv_type = request.query_params.get('type', 'all')
    results  = _run_screen()
    if not results:
        return JSONResponse({"error": "데이터를 불러오지 못했습니다."}, status_code=500)

    foreign_buy = sorted(
        [r for r in results if r['vol_ratio'] > 1.2 and r['price_vs_ma20'] > 0 and r['macd_hist'] > 0],
        key=lambda r: r['vol_ratio'] * (1 + r['price_vs_ma20'] / 100),
        reverse=True
    )[:5]

    foreign_sell = sorted(
        [r for r in results if r['vol_ratio'] > 1.2 and r['price_vs_ma20'] < 0 and r['macd_hist'] < 0],
        key=lambda r: r['vol_ratio'] * (1 - r['price_vs_ma20'] / 100),
        reverse=True
    )[:5]

    inst_buy = sorted(
        [r for r in results if r['score'] >= 3 and r['macd_hist'] > 0],
        key=lambda r: (r['score'], r['macd_hist']),
        reverse=True
    )[:5]

    inst_sell = sorted(
        [r for r in results if r['sell_score'] >= 3 and r['macd_hist'] < 0],
        key=lambda r: (r['sell_score'], -r['macd_hist']),
        reverse=True
    )[:5]

    def slim(items):
        return [{'code': r['code'], 'name': r['name'], 'price': r['price'],
                 'vol_ratio': r['vol_ratio'], 'price_vs_ma20': r['price_vs_ma20'],
                 'macd_hist': r['macd_hist'], 'tags': r['tags']} for r in items]

    if inv_type == 'foreign_buy':
        return {"results": foreign_buy}
    elif inv_type == 'foreign_sell':
        return {"results": foreign_sell}
    elif inv_type == 'inst_buy':
        return {"results": inst_buy}
    elif inv_type == 'inst_sell':
        return {"results": inst_sell}
    else:
        return {
            "foreign_buy":  slim(foreign_buy),
            "foreign_sell": slim(foreign_sell),
            "inst_buy":     slim(inst_buy),
            "inst_sell":    slim(inst_sell),
        }


@router.post('/stock/screen/refresh', dependencies=[Depends(api_require_login)])
def refresh_screen():
    _cache['result'] = None
    _cache['ts']     = 0
    return {"status": "ok", "message": "캐시가 초기화되었습니다."}
