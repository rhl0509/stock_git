"""
routes/advisor_data.py — 종목 어드바이저 데이터 수집 모듈.
stock_advisor.py에서 분리된 외부 API 수집 함수들.
"""
import os, json, urllib.request, urllib.error, urllib.parse
import threading, time
from database.db_connection import get_db_connection


# ══════════════════════════════════════════════════════════
# ── 유틸 ──
# ══════════════════════════════════════════════════════════

def _get_ticker(code):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM kr_stocks WHERE code=%s LIMIT 1", (code,))
            row = cur.fetchone()
            return row['ticker'] if row else code + '.KS'
    except Exception:
        return code + '.KS'
    finally:
        conn.close()

def _http_get(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=headers or {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', errors='replace'))

def _http_get_text(url, headers=None, timeout=8):
    req = urllib.request.Request(url, headers=headers or {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept-Language': 'ko-KR,ko;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        enc = r.headers.get_content_charset() or 'euc-kr'
        return r.read().decode(enc, errors='replace')


# ══════════════════════════════════════════════════════════
# ── DART API ──
# ══════════════════════════════════════════════════════════

_DART_CORP_CACHE = {}   # {code: corp_code}

def _dart_get_corp_code(stock_code):
    """종목코드 → DART corp_code"""
    if stock_code in _DART_CORP_CACHE:
        return _DART_CORP_CACHE[stock_code]
    try:
        key = os.getenv('DART_API_KEY', '')
        url = f"https://opendart.fss.or.kr/api/company.json?crtfc_key={key}&stock_code={stock_code}"
        data = _http_get(url)
        corp_code = data.get('corp_code')
        if corp_code:
            _DART_CORP_CACHE[stock_code] = corp_code
        return corp_code
    except Exception as e:
        print(f"[DART] corp_code 조회 실패: {e}")
        return None

def _fetch_dart(code):
    """DART: 최신 분기 재무제표 + 최근 공시"""
    result = {}
    key = os.getenv('DART_API_KEY', '')
    if not key:
        return result

    try:
        corp_code = _dart_get_corp_code(code)
        if not corp_code:
            return result

        from datetime import datetime
        year = datetime.now().year

        # ── 단일회사 재무제표 (최근 분기) ──
        for reprt_code, label in [
            ('11013', '3분기'), ('11012', '반기'), ('11014', '1분기'), ('11011', '사업보고서')
        ]:
            try:
                url = (
                    f"https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
                    f"?crtfc_key={key}&corp_code={corp_code}"
                    f"&bsns_year={year}&reprt_code={reprt_code}&fs_div=CFS"
                )
                data = _http_get(url)
                if data.get('status') == '000' and data.get('list'):
                    items = {r['account_nm']: r for r in data['list'] if r.get('thstrm_amount')}
                    financials = {}

                    def get_amount(names):
                        for n in names:
                            if n in items:
                                try:
                                    return int(str(items[n]['thstrm_amount']).replace(',',''))
                                except Exception:
                                    pass
                        return None

                    def get_prev_amount(names):
                        for n in names:
                            if n in items and items[n].get('frmtrm_amount'):
                                try:
                                    return int(str(items[n]['frmtrm_amount']).replace(',',''))
                                except Exception:
                                    pass
                        return None

                    rev      = get_amount(['매출액', '수익(매출액)', '영업수익'])
                    op       = get_amount(['영업이익', '영업이익(손실)'])
                    net      = get_amount(['당기순이익', '당기순이익(손실)'])
                    debt     = get_amount(['부채총계'])
                    eq       = get_amount(['자본총계'])
                    prev_rev = get_prev_amount(['매출액', '수익(매출액)', '영업수익'])
                    prev_net = get_prev_amount(['당기순이익', '당기순이익(손실)'])

                    if rev:
                        financials['revenue']       = rev
                        financials['period']        = label
                        financials['year']          = year
                        if op:  financials['operating_income'] = op
                        if net: financials['net_income']       = net
                        if debt and eq and eq > 0:
                            financials['debt_ratio'] = round(debt / eq * 100, 1)
                        if op and rev and rev > 0:
                            financials['op_margin'] = round(op / rev * 100, 1)
                        if prev_rev and prev_rev > 0:
                            financials['revenue_yoy'] = round((rev - prev_rev) / prev_rev * 100, 1)
                        if prev_net is not None and net is not None and prev_net != 0:
                            financials['net_income_yoy'] = round((net - prev_net) / abs(prev_net) * 100, 1)
                        result['financials'] = financials
                        print(f"[DART] 재무제표 수집: {year} {label}")
                        break
            except Exception:
                continue

        # ── 최근 공시 (30일 이내) ──
        try:
            from datetime import timedelta
            today    = datetime.now()
            bgn_date = (today - timedelta(days=30)).strftime('%Y%m%d')
            end_date = today.strftime('%Y%m%d')
            url = (
                f"https://opendart.fss.or.kr/api/list.json"
                f"?crtfc_key={key}&corp_code={corp_code}"
                f"&bgn_de={bgn_date}&end_de={end_date}&page_count=10&sort=date&sort_mth=desc"
            )
            data = _http_get(url)
            if data.get('status') == '000' and data.get('list'):
                disclosures = []
                for item in data['list'][:5]:
                    disclosures.append({
                        'date':  item.get('rcept_dt', ''),
                        'title': item.get('report_nm', ''),
                    })
                result['disclosures'] = disclosures
                print(f"[DART] 공시 {len(disclosures)}건 수집")
        except Exception as e:
            print(f"[DART] 공시 조회 실패: {e}")

    except Exception as e:
        print(f"[DART] 오류: {e}")

    return result


# ══════════════════════════════════════════════════════════
# ── KIS API ──
# ══════════════════════════════════════════════════════════

_KIS_TOKEN     = None
_KIS_TOKEN_EXP = 0

def _kis_get_token():
    """KIS OAuth2 토큰 발급 (캐시)"""
    global _KIS_TOKEN, _KIS_TOKEN_EXP
    now = time.time()
    if _KIS_TOKEN and now < _KIS_TOKEN_EXP - 60:
        return _KIS_TOKEN

    app_key    = os.getenv('KIS_APP_KEY', '')
    app_secret = os.getenv('KIS_APP_SECRET', '')
    if not app_key or not app_secret:
        return None

    try:
        body = json.dumps({
            "grant_type": "client_credentials",
            "appkey":     app_key,
            "appsecret":  app_secret,
        }).encode()
        req = urllib.request.Request(
            "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        _KIS_TOKEN     = data.get('access_token')
        expires_in     = int(data.get('expires_in', 86400))
        _KIS_TOKEN_EXP = now + expires_in
        print(f"[KIS] 토큰 발급 완료 (만료: {expires_in//3600}시간 후)")
        return _KIS_TOKEN
    except Exception as e:
        print(f"[KIS] 토큰 발급 실패: {e}")
        return None

def _kis_get(path, params, tr_id):
    """KIS REST API GET 요청"""
    token = _kis_get_token()
    if not token:
        return None
    app_key    = os.getenv('KIS_APP_KEY', '')
    app_secret = os.getenv('KIS_APP_SECRET', '')
    qs  = urllib.parse.urlencode(params)
    url = f"https://openapi.koreainvestment.com:9443{path}?{qs}"
    req = urllib.request.Request(url, headers={
        "authorization":  f"Bearer {token}",
        "appkey":         app_key,
        "appsecret":      app_secret,
        "tr_id":          tr_id,
        "Content-Type":   "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

def _fetch_kis(code):
    """KIS: 기관/외인 수급 + 투자자별 동향"""
    result = {}
    account_no = os.getenv('KIS_ACCOUNT_NO', '')
    if not account_no:
        return result

    try:
        # ── 투자자별 매매동향 (5일) ──
        from datetime import datetime, timedelta
        today    = datetime.now().strftime('%Y%m%d')
        ago5     = (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')

        data = _kis_get(
            '/uapi/domestic-stock/v1/quotations/inquire-investor',
            {
                'FID_COND_MRKT_DIV_CODE': 'J',
                'FID_INPUT_ISCD':         code,
                'FID_INPUT_DATE_1':       ago5,
                'FID_INPUT_DATE_2':       today,
                'FID_PERIOD_DIV_CODE':    'D',
            },
            'FHKST130010000'
        )

        if data and data.get('rt_cd') == '0' and data.get('output'):
            rows = data['output'][:5]
            inst_net  = sum(int(r.get('inst_ntby_qty',  0) or 0) for r in rows)
            frgn_net  = sum(int(r.get('frgn_ntby_qty',  0) or 0) for r in rows)
            prgm_net  = sum(int(r.get('prgm_ntby_qty',  0) or 0) for r in rows)
            result['investor'] = {
                'inst_net_5d':  inst_net,
                'frgn_net_5d':  frgn_net,
                'prgm_net_5d':  prgm_net,
                'inst_trend':   '매수우위' if inst_net > 0 else '매도우위',
                'frgn_trend':   '매수우위' if frgn_net > 0 else '매도우위',
                'days':         len(rows),
            }
            print(f"[KIS] 수급: 기관 {inst_net:+,} 외인 {frgn_net:+,} 프로그램 {prgm_net:+,}")

    except Exception as e:
        print(f"[KIS] 수급 조회 실패: {e}")

    return result


# ══════════════════════════════════════════════════════════
# ── 한국은행 ECOS API ──
# ══════════════════════════════════════════════════════════

def _fetch_bok():
    """한국은행: 기준금리, 원달러 환율, 국채금리"""
    result = {}
    key = os.getenv('BOK_API_KEY', '')
    if not key:
        return result

    from datetime import datetime, timedelta
    today = datetime.now().strftime('%Y%m%d')
    ago30 = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

    def bok_get(stat_code, item_code, label):
        try:
            url = (
                f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr"
                f"/1/5/{stat_code}/DD/{ago30}/{today}/{item_code}"
            )
            data = _http_get(url)
            rows = data.get('StatisticSearch', {}).get('row', [])
            if rows:
                latest = rows[-1]
                prev   = rows[-5] if len(rows) >= 5 else rows[0]
                val    = float(latest.get('DATA_VALUE', 0))
                prev_v = float(prev.get('DATA_VALUE', 0))
                result[label] = {
                    'value':  val,
                    'date':   latest.get('TIME', ''),
                    'change': round(val - prev_v, 4),
                }
        except Exception as e:
            print(f"[BOK] {label} 조회 실패: {e}")

    bok_get('722Y001', '0101000', 'base_rate')    # 기준금리
    bok_get('036Y001', '09602',   'usd_krw')      # 원달러 환율
    bok_get('817Y002', '010190000', 'bond_10y')   # 국채 10년

    if result:
        print(f"[BOK] 수집: {list(result.keys())}")
    return result


# ══════════════════════════════════════════════════════════
# ── yfinance (기술적 분석 전용) ──
# ══════════════════════════════════════════════════════════

def _fetch_yfinance(ticker):
    try:
        import yfinance as yf
        import numpy as np

        t    = yf.Ticker(ticker)
        hist = t.history(period='6mo')
        info = t.info

        if hist.empty or len(hist) < 20:
            return {}

        close   = hist['Close'].values.tolist()
        volume  = hist['Volume'].values.tolist()
        high_l  = hist['High'].values.tolist()
        low_l   = hist['Low'].values.tolist()
        current = close[-1]

        def ma(d, n):
            return round(float(np.mean(d[-n:])), 0) if len(d) >= n else None

        # RSI(14)
        rsi_val = None
        if len(close) >= 15:
            diff = [close[i] - close[i-1] for i in range(-14, 0)]
            gain = float(np.mean([d for d in diff if d > 0] or [0]))
            loss = float(np.mean([-d for d in diff if d < 0] or [0]))
            rsi_val = round(100 - 100/(1 + gain/loss), 1) if loss else 100.0

        # 볼린저밴드(20)
        bb_up = bb_dn = None
        if len(close) >= 20:
            s = close[-20:]
            m, std = float(np.mean(s)), float(np.std(s))
            bb_up, bb_dn = round(m + 2*std, 0), round(m - 2*std, 0)

        # MACD(12,26,9)
        macd_line = macd_sig = macd_hist = None
        if len(close) >= 35:
            def ema_s(d, n):
                k = 2/(n+1); r = [float(np.mean(d[:n]))]
                for v in d[n:]: r.append(r[-1]*(1-k)+v*k)
                return r
            e12 = ema_s(close, 12); e26 = ema_s(close, 26)
            ln  = len(e26)
            ml  = [e12[-(ln-i)] - e26[i] for i in range(ln)]
            if len(ml) >= 9:
                sl = ema_s(ml, 9)
                macd_line = round(ml[-1], 1)
                macd_sig  = round(sl[-1], 1)
                macd_hist = round(ml[-1] - sl[-1], 1)

        # ATR(14)
        atr = stop15 = stop20 = None
        if len(close) >= 15:
            trs = [max(high_l[i]-low_l[i], abs(high_l[i]-close[i-1]), abs(low_l[i]-close[i-1]))
                   for i in range(-14, 0)]
            atr    = round(float(np.mean(trs)), 0)
            stop15 = round(current - 1.5*atr, 0)
            stop20 = round(current - 2.0*atr, 0)

        # 피보나치 (52주 기준)
        w52_high = max(high_l[-252:]) if len(high_l) >= 252 else max(high_l)
        w52_low  = min(low_l[-252:])  if len(low_l)  >= 252 else min(low_l)
        rng      = w52_high - w52_low
        w52_pct  = round((current - w52_low) / rng * 100, 1) if rng else 50
        fib = {}
        if rng > 0:
            for p in [23.6, 38.2, 50.0, 61.8, 78.6]:
                fib[str(p)] = round(w52_high - rng * p/100, 0)

        # 이동평균 이격도 ((현재가 - MAn) / MAn * 100)
        ma5_val  = float(np.mean(close[-5:]))  if len(close) >= 5  else None
        ma20_val = float(np.mean(close[-20:])) if len(close) >= 20 else None
        ma60_val = float(np.mean(close[-60:])) if len(close) >= 60 else None
        ma5_dev  = round((current - ma5_val)  / ma5_val  * 100, 2) if ma5_val  else None
        ma20_dev = round((current - ma20_val) / ma20_val * 100, 2) if ma20_val else None
        ma60_dev = round((current - ma60_val) / ma60_val * 100, 2) if ma60_val else None

        # 거래량
        avg20 = float(np.mean(volume[-20:])) if len(volume) >= 20 else None
        avg5  = float(np.mean(volume[-5:]))  if len(volume) >= 5  else None
        vol_ratio = round(avg5/avg20, 2) if avg20 else None

        # 코스피 방향성
        kospi = {}
        try:
            kh = yf.Ticker('^KS11').history(period='1mo')
            if not kh.empty and len(kh) >= 5:
                kc = kh['Close'].values.tolist()
                kospi = {
                    'current':   round(kc[-1], 2),
                    'change_1w': round((kc[-1]-kc[-5])/kc[-5]*100, 2),
                    'change_1m': round((kc[-1]-kc[0])/kc[0]*100, 2),
                    'trend':     '상승' if kc[-1] > kc[-5] else '하락',
                }
        except Exception: pass

        # yfinance 재무 (보완용)
        yf_per = info.get('trailingPE') or info.get('forwardPE')
        yf_pbr = info.get('priceToBook')
        yf_roe = None
        try:
            ni = info.get('netIncomeToCommon'); bv = info.get('bookValue'); sh = info.get('sharesOutstanding')
            if ni and bv and sh and bv > 0: yf_roe = round(ni/(bv*sh)*100, 2)
        except Exception: pass
        yf_eps = info.get('trailingEps') or info.get('forwardEps')
        yf_div = info.get('dividendYield')
        if yf_div: yf_div = round(yf_div*100, 2)

        return {
            'current_price': round(current, 0),
            'ma5': ma(close,5), 'ma20': ma(close,20),
            'ma60': ma(close,60), 'ma120': ma(close,120),
            'rsi': rsi_val,
            'bb_upper': bb_up, 'bb_lower': bb_dn,
            'macd': macd_line, 'macd_signal': macd_sig, 'macd_hist': macd_hist,
            'ma5_dev': ma5_dev, 'ma20_dev': ma20_dev, 'ma60_dev': ma60_dev,
            'atr': atr, 'stop_atr15': stop15, 'stop_atr20': stop20,
            'fib': fib,
            'w52_high': round(w52_high,0), 'w52_low': round(w52_low,0), 'w52_position': w52_pct,
            'vol_ratio_5_20': vol_ratio,
            'kospi': kospi,
            'sector': info.get('sector') or info.get('industry',''), 'beta': info.get('beta'),
            'yf_per': round(yf_per,2) if yf_per else None,
            'yf_pbr': round(yf_pbr,2) if yf_pbr else None,
            'yf_roe': yf_roe,
            'yf_eps': round(yf_eps,0) if yf_eps else None,
            'yf_div': yf_div,
        }
    except Exception as e:
        print(f"[Advisor] yfinance 오류: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# ── 네이버 금융 애널리스트 컨센서스 ──
# ══════════════════════════════════════════════════════════

def _fetch_naver_consensus(code):
    """
    애널리스트 컨센서스 수집.

    소스 우선순위:
    1) 에프앤가이드 공개 API (wisereport) - 가장 정확
    2) 네이버 금융 리서치 페이지 HTML - 종목 코드 검증 포함
    3) 없으면 None 반환 (소형주 정상)
    """
    import re
    result = {}

    headers = {
        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Accept':          'application/json, text/html, */*',
    }

    # ── 1차: 에프앤가이드 / wisereport 공개 API ──
    try:
        url = (
            f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"
            f"?cmp_cd={code}&cn="
        )
        headers_wr = {**headers, 'Referer': 'https://finance.naver.com/'}
        raw = _http_get_text(url, headers=headers_wr)

        tp_match = re.search(
            r'목표주가[^<]{0,30}([0-9]{2,3},[0-9]{3})',
            raw
        )
        if tp_match:
            val = int(tp_match.group(1).replace(',', ''))
            result['target_price'] = val
            print(f"[Consensus] wisereport 목표주가: {val:,}원")

        for op in ['강력매수', '매수', '중립', '매도']:
            if op in raw[:30000]:
                result.setdefault('dominant_opinion', op)
                break

    except Exception as e:
        print(f"[Consensus] wisereport 실패: {e}")

    # ── 2차: 네이버 금융 리서치 (종목코드 명시 검증) ──
    if not result.get('target_price'):
        try:
            url = (
                f"https://finance.naver.com/research/company_list.naver"
                f"?searchType=itemCode&itemCode={code}&page=1"
            )
            raw = _http_get_text(url, headers={**headers, 'Referer': 'https://finance.naver.com/'})

            if code not in raw and len(raw) < 5000:
                print(f"[Consensus] 리서치 페이지 없음: {code}")
                return result

            rows = re.findall(r'<tr[^>]*class="[^"]*"[^>]*>(.*?)</tr>', raw, re.DOTALL)

            target_list = []
            opinion_list = []

            for row in rows[:15]:
                number_tds = re.findall(r'<td[^>]*class="[^"]*number[^"]*"[^>]*>\s*([0-9,]+)\s*</td>', row)

                for n_str in number_tds:
                    try:
                        val = int(n_str.replace(',', ''))
                        if 1000 <= val <= 5000000:
                            target_list.append(val)
                    except Exception:
                        pass

                for op in ['강력매수', '매수', '중립', '매도', '강력매도']:
                    if op in row:
                        opinion_list.append(op)

            if target_list:
                target_list.sort()
                trim = max(1, len(target_list) // 5)
                trimmed = target_list[trim:-trim] if len(target_list) > 4 else target_list
                median_tp = trimmed[len(trimmed)//2]
                result['target_price']  = median_tp
                result['target_sample'] = len(target_list)
                print(f"[Consensus] 리서치 {len(target_list)}개 → 중간값 목표주가 {median_tp:,}원")

            if opinion_list:
                from collections import Counter
                cnt = Counter(opinion_list)
                result['opinions']         = dict(cnt)
                result['total_count']      = sum(cnt.values())
                result['dominant_opinion'] = cnt.most_common(1)[0][0]
                buy = cnt.get('강력매수', 0) + cnt.get('매수', 0)
                result['buy_ratio'] = round(buy / result['total_count'] * 100, 1)
                print(f"[Consensus] 의견 {result['total_count']}건: {result['dominant_opinion']}")

        except Exception as e:
            print(f"[Consensus] 리서치 파싱 실패: {e}")

    if not result:
        print(f"[Consensus] {code} 커버리지 없음")
    return result


def _fetch_naver_news(code, limit=5):
    """
    종목 뉴스 수집.
    1) 네이버 금융 종목 뉴스 페이지 (정확한 패턴)
    2) 네이버 금융 종목 뉴스 모바일 JSON
    """
    import re

    headers_pc = {
        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Referer':         'https://finance.naver.com/',
    }

    # ── 1차: PC 뉴스 페이지 (종목 코드 명시 URL) ──
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
        raw = _http_get_text(url, headers=headers_pc)

        titles = []
        pats = [
            r'<a[^>]+href="/item/news_read[^"]*"[^>]*>\s*([^<]{8,80})\s*</a>',
            r'<td[^>]+class="title"[^>]*>.*?<a[^>]+>([^<]{8,80})</a>',
            r'title="([^"]{8,80})"[^>]*>\s*[^<]+\s*</a>\s*</td>',
        ]

        import html as _html
        for pat in pats:
            found = re.findall(pat, raw, re.DOTALL)
            cleaned = [
                re.sub(r'\s+', ' ', _html.unescape(t)).strip()
                for t in found
                if len(t.strip()) >= 8 and '...' not in t
            ]
            if cleaned:
                titles = cleaned[:limit]
                print(f"[Naver] PC 뉴스 {len(titles)}건")
                return titles

    except Exception as e:
        print(f"[Naver] PC 뉴스 실패: {e}")

    # ── 2차: 네이버 금융 종목 뉴스 API ──
    try:
        url = (
            f"https://finance.naver.com/item/news.naver"
            f"?code={code}&page=1&pageSize={limit}"
        )
        raw = _http_get_text(url, headers=headers_pc)

        import html as _html
        titles = []
        for m in re.finditer(r'<a[^>]+class="[^"]*news[^"]*"[^>]*>([^<]{8,})</a>', raw):
            t = _html.unescape(m.group(1)).strip()
            if t and len(t) >= 8:
                titles.append(t)

        if titles:
            titles = titles[:limit]
            print(f"[Naver] 뉴스 API {len(titles)}건")
            return titles

    except Exception as e:
        print(f"[Naver] 뉴스 API 실패: {e}")

    print(f"[Naver] {code} 뉴스 수집 실패")
    return []


def _fetch_kiwoom(code):
    try:
        from kiwoom_client import kiwoom
        if not kiwoom.market_data_ready(): return {}
        return kiwoom.get_best_price(code) or {}
    except Exception as e:
        print(f"[Advisor] 키움 오류: {e}")
        return {}


def _fetch_short_selling(code: str) -> dict:
    """pykrx 공매도 피처 — XGBoost short_features 재사용 (6시간 캐시)."""
    try:
        from XGBoost_v2.short_features import get_short_features
        result = get_short_features(code)
        if result and any(v > 0 for v in result.values()):
            print(f"[Short] {code}: {result}")
        return result
    except Exception as e:
        print(f"[Short] 공매도 조회 실패: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# ── 통합 데이터 수집 ──
# ══════════════════════════════════════════════════════════

def _collect_analysis_data(code: str) -> dict:
    """데이터 수집 (병렬 스레드). analyze_stock + stream 공용."""
    results = {
        'kw': {}, 'yf': {}, 'dart': {}, 'kis': {},
        'bok': {}, 'news': [], 'consensus': {}, 'ml': {}, 'short': {},
    }

    def run(key, fn, *args):
        try:
            results[key] = fn(*args)
        except Exception as e:
            print(f"[Advisor] {key} 오류: {e}")

    ticker = _get_ticker(code)

    def _run_ml():
        try:
            from routes.stock_ml import get_ml_prediction
            results['ml'] = get_ml_prediction(code, ticker)
        except Exception as e:
            print(f'[ML] 오류: {e}')

    threads = [
        threading.Thread(target=run,    args=('kw',        _fetch_kiwoom,          code)),
        threading.Thread(target=run,    args=('yf',        _fetch_yfinance,        ticker)),
        threading.Thread(target=run,    args=('dart',      _fetch_dart,            code)),
        threading.Thread(target=run,    args=('kis',       _fetch_kis,             code)),
        threading.Thread(target=run,    args=('bok',       _fetch_bok)),
        threading.Thread(target=run,    args=('news',      _fetch_naver_news,      code)),
        threading.Thread(target=run,    args=('consensus', _fetch_naver_consensus, code)),
        threading.Thread(target=run,    args=('short',     _fetch_short_selling,   code)),
        threading.Thread(target=_run_ml),
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)

    kw = results['kw']
    yf = results['yf']

    if results['news']:
        if yf: yf['news'] = results['news']
        else:  yf = {'news': results['news']}

    kw_price = kw.get('price') if kw else None
    if kw_price and yf:
        atr  = yf.get('atr')
        if atr:
            yf['stop_atr15'] = round(kw_price - 1.5 * atr, 0)
            yf['stop_atr20'] = round(kw_price - 2.0 * atr, 0)
        w52h = yf.get('w52_high')
        w52l = yf.get('w52_low')
        if w52h and w52l and w52h != w52l:
            rng = w52h - w52l
            yf['w52_position'] = round((kw_price - w52l) / rng * 100, 1)
            yf['fib'] = {str(p): round(w52h - rng * p / 100, 0)
                         for p in [23.6, 38.2, 50.0, 61.8, 78.6]}
        yf['current_price'] = kw_price

    results['kw'] = kw
    results['yf'] = yf
    return results
