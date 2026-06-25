import logging
import json, re, os, asyncio, threading, time as _time
import numpy as np
import requests as _requests
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse, StreamingResponse
from database.db_connection import get_db_connection
from routes.utils import api_require_login, require_login_smart

router = APIRouter(dependencies=[Depends(require_login_smart)])
logger = logging.getLogger(__name__)

_MOVERS_CACHE: dict = {"data": None, "ts": 0.0}
_MOVERS_TTL   = 300
_MOVERS_LOCK  = asyncio.Lock()

_PRICE_CACHE: dict = {}   # {ticker: (price, ts)}
_PRICE_TTL   = 30
_PRICE_LOCK  = threading.Lock()

_INDICES_CACHE: dict = {"data": None, "ts": 0.0}
_INDICES_TTL   = 300
_INDICES_LOCK  = asyncio.Lock()

_NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://m.stock.naver.com/',
    'Accept': 'application/json, text/plain, */*',
}


def _realtime_price(ticker: str) -> float | None:
    import math
    try:
        is_kr = ticker.endswith('.KS') or ticker.endswith('.KQ')
        if is_kr:
            code = ticker.replace('.KS', '').replace('.KQ', '')
            url  = f'https://m.stock.naver.com/api/stock/{code}/basic'
            r    = _requests.get(url, headers=_NAVER_HEADERS, timeout=4)
            raw  = r.json()
            price_str = (raw.get('closePrice') or raw.get('currentPrice')
                         or raw.get('price') or raw.get('stockPrice'))
            if price_str:
                return float(str(price_str).replace(',', ''))
        else:
            import yfinance as yf
            data = yf.Ticker(ticker).history(period='1d', interval='1m')
            if not data.empty:
                v = float(data['Close'].iloc[-1])
                return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        pass
    return None


def _naver_fundamentals(kr_code: str) -> dict:
    try:
        hdrs = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://finance.naver.com'}
        url = f'https://finance.naver.com/item/main.naver?code={kr_code}'
        r   = _requests.get(url, headers=hdrs, timeout=6)
        r.encoding = 'euc-kr'
        def _num(field):
            m = re.search(rf'id="{field}">([\d,.N/A-]+)<', r.text)
            if not m or m.group(1) in ('N/A', '-', ''):
                return None
            return m.group(1).replace(',', '')
        per = _num('_per'); eps = _num('_eps'); pbr = _num('_pbr')
        return {
            'per': round(float(per), 2) if per else None,
            'eps': int(float(eps))      if eps else 0,
            'pbr': round(float(pbr), 2) if pbr else None,
        }
    except Exception:
        return {'per': None, 'eps': 0, 'pbr': None}


@router.get('/price/{ticker}')
async def get_price(ticker: str):
    now = _time.time()
    with _PRICE_LOCK:
        cached = _PRICE_CACHE.get(ticker)
    if cached and now - cached[1] < _PRICE_TTL:
        return {"symbol": ticker, "price": cached[0]}

    def _fetch():
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="2d", interval="1d")
        if data.empty:
            return None
        return round(float(data['Close'].iloc[-1]), 2)

    try:
        price = await asyncio.to_thread(_fetch)
        if price is None:
            return JSONResponse({"error": "종목을 찾을 수 없거나 데이터를 가져오지 못했습니다."}, status_code=404)
        with _PRICE_LOCK:
            _PRICE_CACHE[ticker] = (price, now)
        return {"symbol": ticker, "price": price}
    except Exception:
        return JSONResponse({"error": "가격 조회 중 오류가 발생했습니다."}, status_code=500)


def _fetch_batch_sync(tickers: list) -> dict:
    import math, yfinance as yf
    now = _time.time()
    with _PRICE_LOCK:
        uncached = [t for t in tickers if t not in _PRICE_CACHE or now - _PRICE_CACHE[t][1] >= _PRICE_TTL]
    if uncached:
        try:
            if len(uncached) == 1:
                data = yf.Ticker(uncached[0]).history(period='2d', interval='1d')
                if not data.empty:
                    v = float(data['Close'].iloc[-1])
                    if not (math.isnan(v) or math.isinf(v)):
                        with _PRICE_LOCK:
                            _PRICE_CACHE[uncached[0]] = (round(v, 2), now)
            else:
                raw = yf.download(uncached, period='2d', interval='1d', auto_adjust=True, progress=False, threads=True)
                if raw is not None and not raw.empty:
                    close_df = raw['Close']
                    updates = {}
                    for sym in uncached:
                        try:
                            if sym not in close_df.columns:
                                continue
                            prices = close_df[sym].dropna()
                            if prices.empty:
                                continue
                            v = float(prices.iloc[-1])
                            if not (math.isnan(v) or math.isinf(v)):
                                updates[sym] = (round(v, 2), now)
                        except Exception:
                            pass
                    with _PRICE_LOCK:
                        _PRICE_CACHE.update(updates)
        except Exception:
            pass
    with _PRICE_LOCK:
        return {t: _PRICE_CACHE[t][0] for t in tickers if t in _PRICE_CACHE}


@router.get('/prices/batch')
async def get_prices_batch(request: Request):
    raw = request.query_params.get('symbols', '')
    tickers = [t.strip() for t in raw.split(',') if t.strip()][:20]
    if not tickers:
        return {}
    return await asyncio.to_thread(_fetch_batch_sync, tickers)


_MOVERS_KR_SYMBOLS = [
    # 대형주 (시가총액 상위)
    '005930.KS', '000660.KS', '373220.KS', '207940.KS', '005380.KS',
    '068270.KS', '000270.KS', '051910.KS', '035420.KS', '035720.KS',
    '247540.KS', '086520.KS', '003670.KS', '066570.KS', '105560.KS',
    '017670.KS', '323410.KS', '259960.KS', '352820.KS', '012330.KS',
    # 추가 주요 KOSPI 종목
    '055550.KS', '316140.KS', '003490.KS', '032830.KS', '086790.KS',
    '018260.KS', '028260.KS', '096770.KS', '011200.KS', '009150.KS',
    '010130.KS', '000810.KS', '034730.KS', '033780.KS', '015760.KS',
    '009830.KS', '009540.KS', '064350.KS', '042660.KS', '326030.KS',
    '010950.KS', '011070.KS', '012750.KS', '139480.KS', '298050.KS',
    '271560.KS', '450080.KS', '263750.KS', '377300.KS', '006400.KS',
]
_MOVERS_US_SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META', 'GOOGL', 'AMD', 'NFLX', 'INTC',
                      'BABA', 'PLTR', 'COIN', 'SOFI', 'RIVN']
_MOVERS_KR_NAMES = {
    '005930.KS': '삼성전자',    '000660.KS': 'SK하이닉스',   '373220.KS': 'LG에너지솔루션',
    '207940.KS': '삼성바이오로직스', '005380.KS': '현대차',    '068270.KS': '셀트리온',
    '000270.KS': '기아',        '051910.KS': 'LG화학',       '035420.KS': '네이버',
    '035720.KS': '카카오',      '247540.KS': '에코프로비엠',  '086520.KS': '에코프로',
    '003670.KS': '포스코퓨처엠', '066570.KS': 'LG전자',      '105560.KS': 'KB금융',
    '017670.KS': 'SK텔레콤',   '323410.KS': '카카오뱅크',    '259960.KS': '크래프톤',
    '352820.KS': '하이브',      '012330.KS': '현대모비스',
    '055550.KS': '신한지주',    '316140.KS': '우리금융지주',  '003490.KS': '대한항공',
    '032830.KS': '삼성생명',    '086790.KS': '하나금융지주',  '018260.KS': '삼성에스디에스',
    '028260.KS': '삼성물산',    '096770.KS': 'SK이노베이션',  '011200.KS': 'HMM',
    '009150.KS': '삼성전기',    '010130.KS': '고려아연',      '000810.KS': '삼성화재',
    '034730.KS': 'SK',         '033780.KS': 'KT&G',         '015760.KS': '한국전력',
    '009830.KS': '한화솔루션',  '009540.KS': 'HD한국조선해양','064350.KS': '현대로템',
    '042660.KS': 'HD현대중공업','326030.KS': 'SK바이오팜',    '010950.KS': 'S-Oil',
    '011070.KS': 'LG이노텍',   '012750.KS': '에스원',        '139480.KS': '이마트',
    '298050.KS': '효성첨단소재','271560.KS': '오리온',        '450080.KS': '카카오페이',
    '263750.KS': '펄어비스',    '377300.KS': '카카오게임즈',  '006400.KS': '삼성SDI',
}


def _fetch_movers_sync() -> dict:
    """KR+US 모버 데이터. kr_all에 한국 전체 종목 결과도 포함."""
    import math, yfinance as yf
    all_syms = _MOVERS_KR_SYMBOLS + _MOVERS_US_SYMBOLS
    try:
        # 2d는 전일 종가가 NaN으로 와서 종목이 통째로 누락되는 경우가 잦음 → 5d
        raw = yf.download(all_syms, period='5d', auto_adjust=True, progress=False, threads=True)
    except Exception:
        return {'gainers': [], 'losers': [], 'kr_all': []}
    if raw is None or raw.empty:
        return {'gainers': [], 'losers': [], 'kr_all': []}
    try:
        close_df  = raw['Close']
        volume_df = raw.get('Volume', None)
    except (KeyError, TypeError):
        return {'gainers': [], 'losers': [], 'kr_all': []}

    result = []
    for sym in all_syms:
        try:
            if sym not in close_df.columns:
                continue
            prices = close_df[sym].dropna()
            if len(prices) < 2:
                continue
            price = float(prices.iloc[-1])
            prev  = float(prices.iloc[-2])
            if not prev or math.isnan(price) or math.isinf(price):
                continue
            chg  = (price - prev) / prev * 100
            vol  = 0
            if volume_df is not None and sym in volume_df.columns:
                vols = volume_df[sym].dropna()
                if not vols.empty:
                    vol = int(float(vols.iloc[-1]) or 0)
            name = _MOVERS_KR_NAMES.get(sym, sym.replace('.KS', '').replace('.KQ', ''))
            result.append({
                'symbol': sym, 'name': name,
                'price': round(price, 2), 'change': round(chg, 2),
                'volume': vol,
                'trade_value': round(price * vol),   # 거래대금 proxy
            })
        except Exception:
            continue

    # 전체/KR 분리
    kr_result = [s for s in result if '.KS' in s['symbol'] or '.KQ' in s['symbol']]
    result.sort(key=lambda x: x['change'], reverse=True)

    return {
        'gainers': result[:5],
        'losers':  list(reversed(result))[:5],
        'kr_all':  kr_result,   # 한국 전체 (investor 탭용)
    }


@router.get('/market-movers')
async def get_market_movers():
    if _MOVERS_CACHE['data'] is not None and _time.time() - _MOVERS_CACHE['ts'] < _MOVERS_TTL:
        return _MOVERS_CACHE['data']
    async with _MOVERS_LOCK:
        if _MOVERS_CACHE['data'] is None or _time.time() - _MOVERS_CACHE['ts'] >= _MOVERS_TTL:
            data = await asyncio.to_thread(_fetch_movers_sync)
            _MOVERS_CACHE['data'] = data
            _MOVERS_CACHE['ts']   = _time.time()
    return _MOVERS_CACHE['data']


# ── React SPA alias: /api/market/movers  (gainers→rising, losers→falling, change→change_pct) ──
@router.get('/api/market/movers')
async def api_market_movers():
    if _MOVERS_CACHE['data'] is not None and _time.time() - _MOVERS_CACHE['ts'] < _MOVERS_TTL:
        raw = _MOVERS_CACHE['data']
    else:
        async with _MOVERS_LOCK:
            if _MOVERS_CACHE['data'] is None or _time.time() - _MOVERS_CACHE['ts'] >= _MOVERS_TTL:
                raw = await asyncio.to_thread(_fetch_movers_sync)
                _MOVERS_CACHE['data'] = raw
                _MOVERS_CACHE['ts']   = _time.time()
        raw = _MOVERS_CACHE['data']

    def _fmt(items):
        return [{'code': s.get('symbol', ''), 'name': s.get('name', ''),
                 'price': s.get('price'), 'change_pct': s.get('change')} for s in items]

    return {'rising': _fmt(raw.get('gainers', [])), 'falling': _fmt(raw.get('losers', []))}


@router.get('/stock-analysis/{ticker}')
def stock_analysis(ticker: str):
    import math, yfinance as yf
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period='6mo').dropna(subset=['Close'])
        if hist.empty or len(hist) < 30:
            return JSONResponse({'error': '데이터 부족'}, status_code=404)

        def _clean(v):
            if v is None: return None
            try: return None if (math.isnan(v) or math.isinf(v)) else v
            except (TypeError, ValueError): return None

        close  = [_clean(v) for v in hist['Close'].values.tolist()]
        high   = [_clean(v) for v in hist['High'].values.tolist()]
        low    = [_clean(v) for v in hist['Low'].values.tolist()]
        volume = [_clean(v) or 0 for v in hist['Volume'].values.tolist()]
        dates  = [str(d.date()) for d in hist.index]

        def ma(data, n):
            result = [None] * (n - 1)
            for i in range(n - 1, len(data)):
                result.append(round(float(np.mean(data[i - n + 1:i + 1])), 2))
            return result

        ma5 = ma(close, 5); ma20 = ma(close, 20); ma60 = ma(close, 60)
        bb_mid, bb_up, bb_dn = [], [], []
        for i in range(len(close)):
            if i < 19:
                bb_mid.append(None); bb_up.append(None); bb_dn.append(None)
            else:
                s = close[i - 19:i + 1]; m = float(np.mean(s)); d = float(np.std(s))
                bb_mid.append(round(m, 2)); bb_up.append(round(m + 2 * d, 2)); bb_dn.append(round(m - 2 * d, 2))

        rsi_list = [None] * 14
        for i in range(14, len(close)):
            diff = [close[j] - close[j - 1] for j in range(i - 13, i + 1)]
            gain = float(np.mean([d for d in diff if d > 0] or [0]))
            loss = float(np.mean([-d for d in diff if d < 0] or [0]))
            rs   = gain / loss if loss else 100
            rsi_list.append(round(100 - 100 / (1 + rs), 2))

        def ema(data, n):
            k = 2 / (n + 1); result = [None] * (n - 1)
            result.append(float(np.mean(data[:n])))
            for i in range(n, len(data)):
                result.append(round(result[-1] * (1 - k) + data[i] * k, 4))
            return result

        ema12 = ema(close, 12); ema26 = ema(close, 26)
        macd_line   = [round(a - b, 4) if a and b else None for a, b in zip(ema12, ema26)]
        valid_macd  = [(i, v) for i, v in enumerate(macd_line) if v is not None]
        signal_line = [None] * len(macd_line)
        if len(valid_macd) >= 9:
            start = valid_macd[8][0]; vals = [v for _, v in valid_macd[:9]]
            signal_line[start] = round(float(np.mean(vals)), 4); k = 2 / 10
            for i in range(start + 1, len(macd_line)):
                if macd_line[i] is not None:
                    signal_line[i] = round(signal_line[i - 1] * (1 - k) + macd_line[i] * k, 4)
        macd_hist = [round(m - s, 4) if m and s else None for m, s in zip(macd_line, signal_line)]

        realtime = _realtime_price(ticker)
        last     = realtime if realtime else close[-1]
        signals  = []

        rsi_val = next((v for v in reversed(rsi_list) if v is not None), None)
        if rsi_val:
            if rsi_val < 30:   signals.append({'label': 'RSI 과매도', 'score': 2,  'desc': f'RSI {rsi_val:.1f} — 반등 가능성'})
            elif rsi_val < 45: signals.append({'label': 'RSI 매수권', 'score': 1,  'desc': f'RSI {rsi_val:.1f} — 매수 우호적'})
            elif rsi_val > 70: signals.append({'label': 'RSI 과매수', 'score': -2, 'desc': f'RSI {rsi_val:.1f} — 조정 주의'})
            elif rsi_val > 55: signals.append({'label': 'RSI 매도권', 'score': -1, 'desc': f'RSI {rsi_val:.1f} — 과열 경계'})
            else:              signals.append({'label': 'RSI 중립',   'score': 0,  'desc': f'RSI {rsi_val:.1f} — 중립 구간'})

        m_last = next((v for v in reversed(macd_hist) if v is not None), None)
        m_prev = next((v for i, v in enumerate(reversed(macd_hist)) if v is not None and i > 0), None)
        if m_last is not None and m_prev is not None:
            if m_last > 0 and m_prev <= 0:   signals.append({'label': 'MACD 골든크로스', 'score': 2,  'desc': 'MACD 상향 돌파 — 강한 매수 신호'})
            elif m_last < 0 and m_prev >= 0: signals.append({'label': 'MACD 데드크로스', 'score': -2, 'desc': 'MACD 하향 돌파 — 강한 매도 신호'})
            elif m_last > 0:                 signals.append({'label': 'MACD 강세', 'score': 1,  'desc': 'MACD 양전 — 상승 추세'})
            else:                            signals.append({'label': 'MACD 약세', 'score': -1, 'desc': 'MACD 음전 — 하락 추세'})

        if bb_up[-1] and bb_dn[-1]:
            if last > bb_up[-1]:    signals.append({'label': '볼린저 상단 돌파', 'score': -1, 'desc': '상단 밴드 초과 — 단기 과매수'})
            elif last < bb_dn[-1]:  signals.append({'label': '볼린저 하단 이탈', 'score': 2,  'desc': '하단 밴드 이탈 — 반등 기대'})
            elif last > bb_mid[-1]: signals.append({'label': '볼린저 상단권', 'score': 1,  'desc': '중심선 위 — 강세 유지'})
            else:                   signals.append({'label': '볼린저 하단권', 'score': -1, 'desc': '중심선 아래 — 약세 구간'})

        if ma5[-1] and ma20[-1] and ma5[-2] and ma20[-2]:
            if ma5[-1] > ma20[-1] and ma5[-2] <= ma20[-2]:   signals.append({'label': '골든크로스 (5·20)', 'score': 2,  'desc': '단기선 상향 돌파 — 매수 신호'})
            elif ma5[-1] < ma20[-1] and ma5[-2] >= ma20[-2]: signals.append({'label': '데드크로스 (5·20)', 'score': -2, 'desc': '단기선 하향 이탈 — 매도 신호'})
            elif ma5[-1] > ma20[-1]: signals.append({'label': '정배열 (5>20)', 'score': 1,  'desc': '이동평균 정배열 — 상승 추세'})
            else:                    signals.append({'label': '역배열 (5<20)', 'score': -1, 'desc': '이동평균 역배열 — 하락 추세'})

        avg_vol = float(np.mean(volume[-20:])) if len(volume) >= 20 else 1
        if volume[-1] > avg_vol * 2:
            signals.append({'label': '거래량 급등', 'score': 1, 'desc': f'평균 대비 {volume[-1] / avg_vol:.1f}배 — 강한 모멘텀'})

        total_score = sum(s['score'] for s in signals)
        if total_score >= 4:    verdict = {'label': '강력 매수', 'color': '#10b981', 'bg': '#ecfdf5', 'icon': 'bi-graph-up-arrow'}
        elif total_score >= 2:  verdict = {'label': '매수',     'color': '#10b981', 'bg': '#ecfdf5', 'icon': 'bi-arrow-up-circle'}
        elif total_score <= -4: verdict = {'label': '강력 매도', 'color': '#f43f5e', 'bg': '#fff1f2', 'icon': 'bi-graph-down-arrow'}
        elif total_score <= -2: verdict = {'label': '매도',     'color': '#f43f5e', 'bg': '#fff1f2', 'icon': 'bi-arrow-down-circle'}
        else:                   verdict = {'label': '중립',     'color': '#f59e0b', 'bg': '#fffbeb', 'icon': 'bi-dash-circle'}

        is_kr = ticker.endswith('.KS') or ticker.endswith('.KQ')
        try:
            info = t.info; name = info.get('longName') or info.get('shortName') or ticker
        except Exception:
            info = {}; name = ticker

        eps = 0; per = None; pbr = None
        if is_kr:
            kr_code = ticker.replace('.KS', '').replace('.KQ', '')
            fund = _naver_fundamentals(kr_code)
            eps = fund['eps']; per = fund['per']; pbr = fund['pbr']
        else:
            try:
                eps_raw = info.get('trailingEps') or 0; eps = round(float(eps_raw), 2)
                per_v = info.get('trailingPE'); pbr_v = info.get('priceToBook')
                per = round(float(per_v), 1) if per_v else None
                pbr = round(float(pbr_v), 2) if pbr_v else None
            except Exception:
                eps = 0

        return {'dates': dates, 'close': close, 'high': high, 'low': low, 'volume': volume,
                'ma5': ma5, 'ma20': ma20, 'ma60': ma60, 'bb_up': bb_up, 'bb_mid': bb_mid, 'bb_dn': bb_dn,
                'rsi': rsi_list, 'macd': macd_line, 'macd_signal': signal_line, 'macd_hist': macd_hist,
                'signals': signals, 'verdict': verdict, 'total_score': total_score,
                'name': name, 'current_price': round(float(last), 2),
                'is_realtime': realtime is not None, 'eps': eps, 'per': per, 'pbr': pbr, 'is_kr': is_kr}
    except Exception as e:
        logger.error(f'[stock_api] {e}', exc_info=True)
        return JSONResponse({'error': '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/exchange-rate')
def get_exchange_rate():
    import yfinance as yf
    try:
        ticker = yf.Ticker("USDKRW=X")
        hist   = ticker.history(period='1d')
        rate   = float(hist['Close'].iloc[-1]) if not hist.empty else 1350.0
        return {"rate": round(rate, 2)}
    except Exception:
        return {"rate": 1350.0}


_INDICES_META = [
    ('KOSPI',  '^KS11',     None),
    ('NASDAQ', '^IXIC',     None),
    ('S&P500', '^GSPC',     None),
    ('KOSDAQ', '^KQ11',     None),
    ('금',     'GC=F',      '$/oz'),
    ('은',     'SI=F',      '$/oz'),
    ('WTI유',  'CL=F',      '$/배럴'),
    ('달러',   'USDKRW=X',  '₩'),
    ('유로',   'EURKRW=X',  '₩'),
    ('엔화',   'JPYKRW=X',  '₩'),
]
_INDICES_SYM_TO_META = {sym: (name, unit) for name, sym, unit in _INDICES_META}


def _fetch_indices_sync() -> list:
    import math, yfinance as yf
    symbols = [sym for _, sym, _ in _INDICES_META]
    try:
        # 2d는 지수(^KS11 등)의 전일 종가가 NaN으로 오는 경우가 잦아 등락률이 0%로 깨짐 → 5d
        raw = yf.download(symbols, period='5d', auto_adjust=True, progress=False, threads=True)
    except Exception:
        return []
    if raw is None or raw.empty:
        return []
    try:
        close_df = raw['Close']
    except (KeyError, TypeError):
        return []
    result = []
    for _, sym, _ in _INDICES_META:
        try:
            if sym not in close_df.columns:
                continue
            prices = close_df[sym].dropna()
            if len(prices) < 1:
                continue
            name, unit = _INDICES_SYM_TO_META[sym]
            price = float(prices.iloc[-1])
            if math.isnan(price) or math.isinf(price):
                continue
            # 전일 종가가 없으면 0%로 속이지 않고 None (프론트는 '-' 표시)
            chg = None
            if len(prices) >= 2:
                prev = float(prices.iloc[-2])
                if prev and not (math.isnan(prev) or math.isinf(prev)):
                    c = (price - prev) / prev * 100
                    if not (math.isnan(c) or math.isinf(c)):
                        chg = round(c, 2)
            result.append({'name': name, 'price': round(price, 2), 'change': chg, 'unit': unit})
        except Exception:
            continue
    return result


@router.get('/market-indices')
async def get_market_indices():
    if _INDICES_CACHE['data'] is not None and _time.time() - _INDICES_CACHE['ts'] < _INDICES_TTL:
        return _INDICES_CACHE['data']
    async with _INDICES_LOCK:
        if _INDICES_CACHE['data'] is None or _time.time() - _INDICES_CACHE['ts'] >= _INDICES_TTL:
            data = await asyncio.to_thread(_fetch_indices_sync)
            _INDICES_CACHE['data'] = data
            _INDICES_CACHE['ts']   = _time.time()
    return _INDICES_CACHE['data']


# ── React SPA alias: /api/market/indices  (change→change_pct) ──
@router.get('/api/market/indices')
async def api_market_indices():
    if _INDICES_CACHE['data'] is not None and _time.time() - _INDICES_CACHE['ts'] < _INDICES_TTL:
        raw = _INDICES_CACHE['data']
    else:
        async with _INDICES_LOCK:
            if _INDICES_CACHE['data'] is None or _time.time() - _INDICES_CACHE['ts'] >= _INDICES_TTL:
                raw = await asyncio.to_thread(_fetch_indices_sync)
                _INDICES_CACHE['data'] = raw
                _INDICES_CACHE['ts']   = _time.time()
        raw = _INDICES_CACHE['data']
    return [{'name': d['name'], 'price': d['price'], 'change_pct': d.get('change'), 'unit': d.get('unit')}
            for d in raw]


@router.get('/stock-news/{ticker}')
def get_stock_news(ticker: str):
    import yfinance as yf
    try:
        t    = yf.Ticker(ticker)
        news = t.news or []
        result = []
        for n in news[:6]:
            c = n.get('content', {})
            result.append({'title': c.get('title', ''), 'url': c.get('canonicalUrl', {}).get('url', '#'),
                           'publisher': c.get('provider', {}).get('displayName', ''), 'published': c.get('pubDate', '')})
        return result
    except Exception:
        return []


@router.get('/stock-info/{ticker}')
def get_stock_info(ticker: str):
    import yfinance as yf
    try:
        t = yf.Ticker(ticker); info = t.info
        return {'name': info.get('longName') or info.get('shortName', ticker),
                'per': info.get('trailingPE'), 'pbr': info.get('priceToBook'),
                'market_cap': info.get('marketCap'), 'dividend': info.get('dividendYield'),
                'week52_high': info.get('fiftyTwoWeekHigh'), 'week52_low': info.get('fiftyTwoWeekLow'),
                'avg_volume': info.get('averageVolume'), 'sector': info.get('sector') or info.get('industry', '')}
    except Exception:
        return {}


@router.get('/api/stock/short/{code}')
def get_short_ratio(code: str):
    """공매도 잔고 비율 — pykrx 최근 20 거래일."""
    try:
        from pykrx import stock as krx
        from datetime import datetime, timedelta
        import pandas as pd
        end   = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
        df = krx.get_stock_short_balance_by_date(start, end, code)
        if df is None or df.empty:
            return {'ok': False, 'series': []}
        df = df.reset_index()
        date_col  = df.columns[0]
        ratio_col = [c for c in df.columns if '비율' in str(c) or 'ratio' in str(c).lower()]
        vol_col   = [c for c in df.columns if '잔고' in str(c) or 'balance' in str(c).lower()]
        out = []
        for _, row in df.tail(20).iterrows():
            d = row[date_col]
            date_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
            ratio = float(row[ratio_col[0]]) if ratio_col else None
            vol   = int(row[vol_col[0]])     if vol_col   else None
            out.append({'date': date_str, 'ratio': ratio, 'balance': vol})
        latest = out[-1] if out else {}
        return {'ok': True, 'series': out, 'latest_ratio': latest.get('ratio'), 'latest_balance': latest.get('balance')}
    except Exception as e:
        return {'ok': False, 'series': [], 'error': '조회 실패'}


@router.get('/api/stock/news/{code}')
def get_stock_news_kr(code: str, name: str = ''):
    """Naver 종목 뉴스 + 감성 점수 (최근 10건)."""
    import re
    POS = ['상승', '호재', '상향', '성장', '매수', '강세', '서프라이즈', '최고', '흑자', '상장', '수주', '개발', '흑자전환', '급등']
    NEG = ['하락', '악재', '하향', '감소', '매도', '약세', '쇼크', '최저', '적자', '주의', '손실', '리스크', '급락', '적자전환']
    try:
        import requests as _req
        query  = name or code
        url    = f'https://search.naver.com/search.naver?where=news&query={query}+주식&sort=0&pd=4'
        hdrs   = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept-Language': 'ko-KR,ko;q=0.9'}
        r      = _req.get(url, headers=hdrs, timeout=6)
        from bs4 import BeautifulSoup
        soup   = BeautifulSoup(r.text, 'html.parser')
        items  = soup.select('.news_tit')[:10]
        result = []
        for a in items:
            title = a.get_text(strip=True)
            href  = a.get('href', '#')
            pos_cnt = sum(1 for w in POS if w in title)
            neg_cnt = sum(1 for w in NEG if w in title)
            sentiment = 'pos' if pos_cnt > neg_cnt else 'neg' if neg_cnt > pos_cnt else 'neu'
            result.append({'title': title, 'url': href, 'sentiment': sentiment})
        return {'ok': True, 'items': result}
    except Exception as e:
        return {'ok': False, 'items': [], 'error': '조회 실패'}


@router.get('/search-stock')
def search_stock(request: Request):
    import yfinance as yf
    q = request.query_params.get('q', '').strip()
    if not q:
        return []
    try:
        results = yf.Search(q, news_count=0, max_results=8)
        quotes  = results.quotes
        return [{'name': r.get('shortname') or r.get('longname', ''), 'ticker': r.get('symbol', '')}
                for r in quotes
                if r.get('symbol', '').endswith('.KS') or r.get('symbol', '').endswith('.KQ')]
    except Exception:
        return []


@router.get('/watchlist')
def get_watchlist(request: Request, _=Depends(api_require_login)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT watchlist FROM members WHERE id = %s", (request.session['user_no'],))
            row = cursor.fetchone()
            if row and row['watchlist']:
                return json.loads(row['watchlist'])
            return ["AAPL", "005930.KS", "NVDA"]
    except Exception:
        return ["AAPL", "005930.KS", "NVDA"]
    finally:
        conn.close()


@router.post('/watchlist')
def save_watchlist(request: Request, _=Depends(api_require_login), data: dict = Body(default={})):
    watchlist = data.get('watchlist', [])
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE members SET watchlist = %s WHERE id = %s",
                           (json.dumps(watchlist, ensure_ascii=False), request.session['user_no']))
        conn.commit()
        return {"message": "저장 완료"}
    except Exception as e:
        conn.rollback()
        logger.error(f'[stock_api] {e}', exc_info=True)
        return JSONResponse({"error": '서버 오류가 발생했습니다.'}, status_code=500)
    finally:
        conn.close()


@router.get('/stock-compare-data')
def stock_compare_data(request: Request):
    import math, yfinance as yf
    tickers_raw = request.query_params.get('tickers', '')
    tickers = [t.strip() for t in tickers_raw.split(',') if t.strip()]
    if not tickers:
        return JSONResponse({'error': 'tickers 파라미터 필요'}, status_code=400)
    tickers = tickers[:5]

    def _clean(v):
        if v is None: return None
        try: return None if (math.isnan(v) or math.isinf(v)) else round(float(v), 4)
        except: return None

    result = []
    for ticker in tickers:
        try:
            t    = yf.Ticker(ticker)
            hist = t.history(period='6mo').dropna(subset=['Close'])
            if hist.empty or len(hist) < 10:
                result.append({'ticker': ticker, 'error': '데이터 없음'}); continue
            close   = [_clean(v) for v in hist['Close'].values]
            volume  = [int(v) if v == v else 0 for v in hist['Volume'].values]
            dates   = [str(d.date()) for d in hist.index]
            base    = close[0]
            norm    = [round(v / base * 100, 2) if v else None for v in close]
            current = close[-1] or 0
            prev    = close[-2] if len(close) >= 2 else current
            chg_pct = round((current - prev) / prev * 100, 2) if prev else 0
            is_kr   = ticker.endswith('.KS') or ticker.endswith('.KQ')
            try:
                info = t.info; name = info.get('longName') or info.get('shortName') or ticker
            except Exception:
                info = {}; name = ticker
            eps = per = pbr = mkt_cap = None
            if is_kr:
                kr_code = ticker.replace('.KS', '').replace('.KQ', '')
                fund = _naver_fundamentals(kr_code)
                eps = fund['eps']; per = fund['per']; pbr = fund['pbr']; mkt_cap = info.get('marketCap')
            else:
                try:
                    eps = round(float(info.get('trailingEps') or 0), 2)
                    per_v = info.get('trailingPE'); pbr_v = info.get('priceToBook')
                    per = round(float(per_v), 1) if per_v else None
                    pbr = round(float(pbr_v), 2) if pbr_v else None
                    mkt_cap = info.get('marketCap')
                except Exception:
                    pass
            result.append({'ticker': ticker, 'name': name, 'is_kr': is_kr,
                           'dates': dates, 'close': close, 'normalized': norm, 'volume': volume,
                           'current_price': current, 'change_pct': chg_pct,
                           'eps': eps, 'per': per, 'pbr': pbr, 'market_cap': mkt_cap})
        except Exception as e:
            result.append({'ticker': ticker, 'error': '조회 실패'})
    return {'ok': True, 'stocks': result}


# ── React SPA: /api/market/investor  (투자자별 순매수 — pykrx) ──
_INVESTOR_CACHE: dict = {'data': None, 'ts': 0.0}
_INVESTOR_TTL   = 60
_INVESTOR_LOCK  = asyncio.Lock()


def _fetch_investor_sync() -> dict:
    import math
    from datetime import date, timedelta
    from pykrx import stock as pykrx_stock

    today = date.today()
    # 주말 포함 최근 10일 범위 (공휴일 대비 넉넉하게)
    fromdate = (today - timedelta(days=10)).strftime('%Y%m%d')
    todate   = today.strftime('%Y%m%d')

    _억 = 100_000_000  # pykrx는 원(won) 단위 반환 → 억원으로 변환

    def _safe_int(v):
        try:
            f = float(v)
            return 0 if (math.isnan(f) or math.isinf(f)) else int(f)
        except Exception:
            return 0

    # ── KOSPI/KOSDAQ 시장 전체 투자자 동향 (순매수 거래대금, 억원) ──
    def _market_flow(market: str) -> dict:
        try:
            df = pykrx_stock.get_market_trading_value_by_date(fromdate, todate, market)
            if df is None or df.empty:
                return {}
            row = df.iloc[-1]
            cols = df.columns.tolist()
            def _col(keywords):
                for kw in keywords:
                    for c in cols:
                        if kw in c:
                            raw = _safe_int(row[c])
                            return raw // _억  # 원 → 억원
                return 0
            return {
                'foreign':     _col(['외국인합계', '외국인']),
                'institution': _col(['기관합계', '기관']),
                'individual':  _col(['개인']),
            }
        except Exception:
            return {}

    # ── 최근 영업일 찾기 ──
    def _latest_trading_date(market: str) -> str:
        try:
            df = pykrx_stock.get_market_trading_value_by_date(fromdate, todate, market)
            if df is not None and not df.empty:
                return df.index[-1].strftime('%Y%m%d')
        except Exception:
            pass
        return todate

    # ── yfinance 기반 투자자 탭 데이터 ──
    def _kr_investor_list(sort_key: str, ascending: bool, top_n: int = 5) -> list:
        """
        sort_key: 'change' (외국인, 등락률 기준) | 'trade_value' (기관, 거래대금 기준)
        ascending: False=순매수(상위), True=순매도(하위)
        """
        try:
            cached = _MOVERS_CACHE.get('data')
            if cached and cached.get('kr_all'):
                kr_all = cached['kr_all']
            else:
                # 캐시 미스: 로컬 fetch — asyncio.Lock 없는 스레드에서는 캐시 갱신하지 않음
                kr_all = _fetch_movers_sync().get('kr_all', [])
            if not kr_all:
                return []
            sorted_items = sorted(kr_all, key=lambda x: x.get(sort_key, 0), reverse=not ascending)
            return [{'code': s['symbol'].replace('.KS', '').replace('.KQ', ''),
                     'name': s['name'], 'price': int(s.get('price') or 0)}
                    for s in sorted_items[:top_n]]
        except Exception:
            return []

    kospi_flow  = _market_flow('KOSPI')
    kosdaq_flow = _market_flow('KOSDAQ')
    latest      = _latest_trading_date('KOSPI')

    # 외국인: 등락률(%) 기준 / 기관: 거래대금 기준
    latest_iso = f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}T15:30:00+09:00" if len(latest) == 8 else latest

    return {
        'kospi':          kospi_flow,
        'kosdaq':         kosdaq_flow,
        'foreignBuy':     _kr_investor_list('change',      ascending=False),
        'foreignSell':    _kr_investor_list('change',      ascending=True),
        'institutionBuy': _kr_investor_list('trade_value', ascending=False),
        'institutionSell':_kr_investor_list('trade_value', ascending=True),
        'updatedAt':      latest_iso,
    }


@router.get('/api/market/investor')
async def api_market_investor():
    if _INVESTOR_CACHE['data'] is not None and _time.time() - _INVESTOR_CACHE['ts'] < _INVESTOR_TTL:
        return _INVESTOR_CACHE['data']
    async with _INVESTOR_LOCK:
        if _INVESTOR_CACHE['data'] is None or _time.time() - _INVESTOR_CACHE['ts'] >= _INVESTOR_TTL:
            try:
                data = await asyncio.to_thread(_fetch_investor_sync)
            except Exception:
                data = {'kospi': {}, 'kosdaq': {}, 'foreignBuy': [], 'foreignSell': [],
                        'institutionBuy': [], 'institutionSell': []}
            _INVESTOR_CACHE['data'] = data
            _INVESTOR_CACHE['ts']   = _time.time()
    return _INVESTOR_CACHE['data']
