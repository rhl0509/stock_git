"""
routes/recommend.py — 일일 추천 웹 조회 FastAPI 라우터.
"""
import json, logging
from collections import defaultdict
from pathlib import Path
from fastapi import APIRouter, Request, Depends
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from templates_config import render
from database.db_connection import get_db_connection

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_login_smart)])


def _override_names(items: list) -> list:
    """추천 항목의 종목명을 kr_stocks(권위 소스) 기준으로 교정.
    JSON에 박힌 이름이 코드와 불일치(사명변경·오기입)해도 화면엔 코드에 맞는 정확한 이름 표시."""
    if not items:
        return items
    codes = {it.get('code') for it in items if isinstance(it, dict) and it.get('code')}
    if not codes:
        return items
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            ph = ','.join(['%s'] * len(codes))
            cur.execute(f"SELECT code, name FROM kr_stocks WHERE code IN ({ph})", list(codes))
            name_map = {r['code']: r['name'] for r in cur.fetchall()}
        conn.close()
    except Exception as e:
        logger.warning(f'[recommend] 종목명 교정 실패: {e}')
        return items
    for it in items:
        nm = name_map.get(it.get('code'))
        if nm:
            it['name'] = nm
    return items

ROOT        = Path(__file__).parent.parent
MODEL_DIR   = ROOT / 'XGBoost_v2' / 'model'
HISTORY_DIR = MODEL_DIR / 'recommend_history'
HISTORY_DIR_ABS = MODEL_DIR / 'recommend_history_abs'
OHLCV_DIR   = ROOT / 'XGBoost_v2' / 'data' / 'ohlcv'


def _pass_gate(request: Request):
    """AI 추천 데이 패스가 비활성이면 402 JSONResponse 를, 활성이면 None 을 반환."""
    from routes.recommend_pass import has_active_pass
    if not has_active_pass(request.session.get('user_no')):
        return JSONResponse(
            {"ok": False, "pass_required": True,
             "error": "AI 추천받기가 꺼져 있습니다. 내 정보 → AI 추천받기에서 켜주세요."},
            status_code=402)
    return None


def _load_recommend_json(path: Path, error_msg: str):
    if not path.exists():
        return JSONResponse({"ok": False, "error": error_msg}, status_code=404)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return {"ok": True, **json.load(f)}
    except Exception as e:
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/recommend/json')
def recommend_json(request: Request):
    gate = _pass_gate(request)
    if gate is not None:
        return gate
    res = _load_recommend_json(
        MODEL_DIR / 'daily_recommend.json',
        "추천 데이터 없음 — python -m XGBoost_v2.daily_recommend 먼저 실행"
    )
    if isinstance(res, dict) and res.get('ok'):
        for sec in ('triple', 'daily', 'short', 'swing'):
            if isinstance(res.get(sec), list):
                _override_names(res[sec])
    return res


@router.get('/recommend/category/{category}')
def recommend_category(category: str, request: Request):
    if category not in ("daily", "short", "swing", "all"):
        return JSONResponse({"ok": False, "error": "invalid category"}, status_code=400)

    path = MODEL_DIR / 'daily_recommend.json'
    if not path.exists():
        return JSONResponse({"ok": False, "error": "데이터 없음"}, status_code=404)

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = data.get(category, [])
        limit_str = request.query_params.get('limit')
        if limit_str:
            items = items[:int(limit_str)]
        _override_names(items)
        return {
            "ok": True, "category": category,
            "count": len(items), "generated_at": data.get("generated_at"),
            "items": items,
        }
    except Exception as e:
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/recommend/stock/{code}')
def recommend_stock(code: str, request: Request):
    try:
        from XGBoost_v2.predict_v2 import predict_ticker
        name   = request.query_params.get('name', '')
        market = request.query_params.get('market', 'KOSPI')
        result = predict_ticker(code.strip(), name, market)
        if "error" in result:
            return JSONResponse({"ok": False, **result}, status_code=404)
        return {"ok": True, **result}
    except Exception as e:
        logger.error(f"[recommend/stock] {e}")
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/recommend/history')
def recommend_history_list():
    if not HISTORY_DIR.exists():
        return {"ok": True, "dates": []}
    dates = sorted([p.stem for p in HISTORY_DIR.glob("*.json")], reverse=True)
    return {"ok": True, "count": len(dates), "dates": dates}


@router.get('/recommend/history/{date}')
def recommend_history_item(date: str):
    path = HISTORY_DIR / f'{date}.json'
    if not path.exists():
        return JSONResponse({"ok": False, "error": "해당 날짜 데이터 없음"}, status_code=404)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {"ok": True, "date": date, **data}


@router.get('/recommend_abs/history')
def recommend_abs_history_list():
    if not HISTORY_DIR_ABS.exists():
        return {"ok": True, "dates": []}
    dates = sorted([p.stem for p in HISTORY_DIR_ABS.glob("*.json")], reverse=True)
    return {"ok": True, "count": len(dates), "dates": dates}


@router.get('/recommend_abs/history/{date}')
def recommend_abs_history_item(date: str):
    path = HISTORY_DIR_ABS / f'{date}.json'
    if not path.exists():
        return JSONResponse({"ok": False, "error": "해당 날짜 데이터 없음"}, status_code=404)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {"ok": True, "date": date, **data}


@router.get('/recommend/stats')
def recommend_stats(request: Request):
    days_str = request.query_params.get('days', '10')
    days = int(days_str)
    if not HISTORY_DIR.exists():
        return {"ok": True, "stats": []}

    files = sorted(list(HISTORY_DIR.glob("*.json")), reverse=True)[:days]

    stock_stats = {}
    for file in files:
        date_str = file.stem
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue

        for category in ['daily', 'short', 'swing']:
            for item in data.get(category, []):
                code = item.get('code')
                if not code:
                    continue
                if code not in stock_stats:
                    stock_stats[code] = {
                        'code': code,
                        'name': item.get('name', code),
                        'market': item.get('market', ''),
                        'count': 0,
                        'dates': [],
                        'categories': set()
                    }
                stock_stats[code]['count'] += 1
                stock_stats[code]['dates'].append(date_str)
                stock_stats[code]['categories'].add(category)

    result_list = []
    for code, stats in stock_stats.items():
        if stats['count'] > 1:
            stats['categories'] = list(stats['categories'])
            stats['dates'] = sorted(list(set(stats['dates'])), reverse=True)
            stats['recent_date'] = stats['dates'][0]
            result_list.append(stats)

    result_list.sort(key=lambda x: (x['count'], x['recent_date']), reverse=True)

    return {
        "ok": True,
        "analyzed_days": len(files),
        "stats": result_list
    }


@router.get('/recommend/backtest')
def recommend_backtest(request: Request):
    days_str = request.query_params.get('days', '7')
    days = int(days_str)
    if not HISTORY_DIR.exists():
        return {"ok": True, "results": [], "summary": {}}

    from datetime import datetime, timedelta
    from korea_stock_data import KoreaStockData
    import pandas as pd

    files = sorted(list(HISTORY_DIR.glob("*.json")), reverse=True)[:days]

    eval_targets = {}
    earliest_date_str = "20991231"

    for file in files:
        date_str = file.stem
        date_str_no_dash = date_str.replace("-", "")
        if date_str_no_dash < earliest_date_str:
            earliest_date_str = date_str_no_dash

        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue

        for category in ['daily', 'short', 'swing']:
            for item in data.get(category, []):
                code = item.get('code')
                if not code: continue
                if code not in eval_targets:
                    eval_targets[code] = []
                eval_targets[code].append({
                    "date": date_str,
                    "date_no_dash": date_str_no_dash,
                    "target": item.get('target', 0),
                    "stop": item.get('stop', 0),
                    "entry": item.get('entry', 0),
                    "category": category,
                    "name": item.get('name', code),
                    "market": item.get('market', '')
                })

    if not eval_targets:
        return {"ok": True, "results": [], "summary": {}}

    today_str = datetime.now().strftime("%Y%m%d")
    data_api = KoreaStockData()

    results = []
    hit_count = 0
    fail_count = 0
    hold_count = 0

    for code, recs in eval_targets.items():
        try:
            df = data_api.fdr.price(code, earliest_date_str, today_str)
            if df.empty:
                continue

            for rec in recs:
                rec_date = rec['date_no_dash']
                df_sub = df[df.index >= pd.to_datetime(rec_date)]

                status = "HOLD"
                max_price = 0
                min_price = float('inf')
                hit_date = None

                target_p = rec['target']
                stop_p = rec['stop']

                for idx, row in df_sub.iterrows():
                    high = row['High']
                    low = row['Low']

                    if high > max_price: max_price = high
                    if low < min_price: min_price = low

                    if target_p > 0 and high >= target_p:
                        status = "HIT"
                        hit_date = idx.strftime("%Y-%m-%d")
                        break
                    if stop_p > 0 and low <= stop_p:
                        status = "FAIL"
                        hit_date = idx.strftime("%Y-%m-%d")
                        break

                if status == "HIT": hit_count += 1
                elif status == "FAIL": fail_count += 1
                else: hold_count += 1

                results.append({
                    "name": rec['name'],
                    "code": code,
                    "market": rec['market'],
                    "category": rec['category'],
                    "rec_date": rec['date'],
                    "entry_price": rec['entry'],
                    "target_price": target_p,
                    "stop_price": stop_p,
                    "max_reached": int(max_price) if max_price > 0 else 0,
                    "min_reached": int(min_price) if min_price != float('inf') else 0,
                    "status": status,
                    "hit_date": hit_date
                })
        except Exception as e:
            logger.error(f"Backtest error for {code}: {e}")
            continue

    total_closed = hit_count + fail_count
    hit_rate = (hit_count / total_closed * 100) if total_closed > 0 else 0

    return {
        "ok": True,
        "analyzed_days": len(files),
        "summary": {
            "total": len(results),
            "hit": hit_count,
            "fail": fail_count,
            "hold": hold_count,
            "hit_rate": round(hit_rate, 1)
        },
        "results": sorted(results, key=lambda x: x['rec_date'], reverse=True)
    }


@router.get('/recommend/perf-data')
def recommend_perf_data(request: Request):
    import pandas as pd

    days_str = request.query_params.get('days', '30')
    days = int(days_str)

    if not HISTORY_DIR.exists():
        return {"ok": True, "results": [], "summary": {}}

    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:days]

    all_recs = []
    for file in files:
        date_stem = file.stem
        date_norm = date_stem.replace("-", "")
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue

        for cat in ('daily', 'short', 'swing'):
            for item in data.get(cat, []):
                code = item.get('code')
                if not code:
                    continue
                all_recs.append({
                    'code':            code,
                    'name':            item.get('name', code),
                    'market':          item.get('market', 'KOSPI'),
                    'category':        cat,
                    'source':          item.get('source', 'unknown'),
                    'rec_date':        date_norm,
                    'entry':           float(item.get('entry') or 0),
                    'target':          float(item.get('target') or 0),
                    'stop':            float(item.get('stop') or 0),
                    'confidence':      float(item.get('confidence') or 0),
                    'expected_return': float(item.get('expected_return') or 0),
                })

    if not all_recs:
        return {"ok": True, "results": [], "summary": {}}

    _ohlcv_cache: dict = {}

    def _load_ohlcv(code: str):
        if code in _ohlcv_cache:
            return _ohlcv_cache[code]
        p = OHLCV_DIR / f"{code}.parquet"
        if not p.exists():
            _ohlcv_cache[code] = None
            return None
        try:
            df = pd.read_parquet(p)
            _ohlcv_cache[code] = df
            return df
        except Exception:
            _ohlcv_cache[code] = None
            return None

    results = []
    for rec in all_recs:
        df       = _load_ohlcv(rec['code'])
        status   = 'HOLD'
        ret_pct  = 0.0
        hit_date = None

        entry  = rec['entry']
        target = rec['target']
        stop   = rec['stop']

        if df is not None and entry > 0:
            rec_dt   = pd.to_datetime(rec['rec_date'])
            df_after = df[df.index > rec_dt]

            for idx, row in df_after.iterrows():
                if target > 0 and row['high'] >= target:
                    status   = 'HIT'
                    hit_date = idx.strftime('%Y-%m-%d')
                    ret_pct  = (target - entry) / entry * 100
                    break
                if stop > 0 and row['low'] <= stop:
                    status   = 'FAIL'
                    hit_date = idx.strftime('%Y-%m-%d')
                    ret_pct  = (stop - entry) / entry * 100
                    break

            if status == 'HOLD' and not df_after.empty:
                last_close = float(df_after['close'].iloc[-1])
                ret_pct    = (last_close - entry) / entry * 100

        results.append({**rec,
                        'status':        status,
                        'actual_return': round(ret_pct, 2),
                        'hit_date':      hit_date})

    total  = len(results)
    n_hit  = sum(1 for r in results if r['status'] == 'HIT')
    n_fail = sum(1 for r in results if r['status'] == 'FAIL')
    n_hold = total - n_hit - n_fail
    closed = n_hit + n_fail

    summary = {
        'total':      total,
        'hit':        n_hit,
        'fail':       n_fail,
        'hold':       n_hold,
        'hit_rate':   round(n_hit / closed * 100, 1) if closed else 0,
        'avg_return': round(sum(r['actual_return'] for r in results) / total, 2) if total else 0,
    }

    def _breakdown(key, values):
        out = {}
        for v in values:
            grp = [r for r in results if r[key] == v]
            n   = len(grp)
            h   = sum(1 for r in grp if r['status'] == 'HIT')
            f   = sum(1 for r in grp if r['status'] == 'FAIL')
            cl  = h + f
            out[v] = {
                'total':      n,
                'hit':        h,
                'fail':       f,
                'hold':       n - cl,
                'hit_rate':   round(h / cl * 100, 1) if cl else 0,
                'avg_return': round(sum(r['actual_return'] for r in grp) / n, 2) if n else 0,
            }
        return out

    category_stats = _breakdown('category', ['daily', 'short', 'swing'])
    source_stats   = _breakdown('source',   ['model', 'factor'])

    daily_map = defaultdict(list)
    for r in results:
        daily_map[r['rec_date']].append(r)

    timeline   = []
    cum_return = 0.0
    for date in sorted(daily_map):
        day   = daily_map[date]
        n     = len(day)
        h     = sum(1 for r in day if r['status'] == 'HIT')
        cl    = h + sum(1 for r in day if r['status'] == 'FAIL')
        avg_r = sum(r['actual_return'] for r in day) / n if n else 0
        cum_return += avg_r
        timeline.append({
            'date':       date,
            'n_recs':     n,
            'hit':        h,
            'closed':     cl,
            'hit_rate':   round(h / cl * 100, 1) if cl else 0,
            'avg_return': round(avg_r, 2),
            'cum_return': round(cum_return, 2),
        })

    return {
        'ok':            True,
        'analyzed_days': len(list(files)),
        'summary':       summary,
        'category_stats': category_stats,
        'source_stats':   source_stats,
        'timeline':       timeline,
        'results':        sorted(results, key=lambda x: x['rec_date'], reverse=True),
    }


@router.get('/recommend')
def recommend_dashboard(request: Request):
    return render(request, 'stock/recommend.html')


@router.get('/recommend_abs')
def recommend_abs_dashboard(request: Request):
    return render(request, 'stock/recommend_abs.html')


@router.get('/recommend_abs/json')
def recommend_abs_json(request: Request):
    gate = _pass_gate(request)
    if gate is not None:
        return gate
    res = _load_recommend_json(
        MODEL_DIR / 'daily_recommend_abs.json',
        "데이터 없음 — 추천 재생성 버튼을 눌러주세요"
    )
    if isinstance(res, dict) and res.get('ok'):
        for sec in ('triple', 'daily', 'short', 'swing'):
            if isinstance(res.get(sec), list):
                _override_names(res[sec])
    return res


@router.get('/recommend/market_context')
def recommend_market_context():
    try:
        from XGBoost_v2.global_features import get_us_sector_snapshot
        data = get_us_sector_snapshot()
        return {"ok": True, **data}
    except Exception as e:
        logger.error(f"[market_context] {e}")
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/recommend/kr_sector_context')
def recommend_kr_sector_context():
    try:
        from XGBoost_v2.global_features import get_kr_sector_snapshot
        data = get_kr_sector_snapshot()
        return {"ok": True, **data}
    except Exception as e:
        logger.error(f"[kr_sector_context] {e}")
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/recommend/kr_sector_stocks')
def recommend_kr_sector_stocks(request: Request):
    sector_no_str = request.query_params.get('no')
    if not sector_no_str:
        return JSONResponse({"ok": False, "error": "no 파라미터 필요"}, status_code=400)
    sector_no = int(sector_no_str)
    try:
        from XGBoost_v2.global_features import get_kr_sector_stocks, _KR_STOCKS_CACHE_DIR
        if request.query_params.get('refresh') == '1':
            ((_KR_STOCKS_CACHE_DIR) / f'{sector_no}.json').unlink(missing_ok=True)
        stocks = get_kr_sector_stocks(sector_no)

        recommended_codes: set = set()
        for fname in ('daily_recommend.json', 'daily_recommend_abs.json'):
            p = MODEL_DIR / fname
            if not p.exists():
                continue
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    rec = json.load(f)
                for cat in ('daily', 'short', 'swing', 'all'):
                    for item in rec.get(cat, []):
                        if item.get('code'):
                            recommended_codes.add(item['code'])
            except Exception:
                pass

        for s in stocks:
            s['ai_pick'] = s['code'] in recommended_codes

        return {"ok": True, "stocks": stocks, "count": len(stocks)}
    except Exception as e:
        logger.error(f"[kr_sector_stocks] no={sector_no}: {e}")
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/recommend/us_sector_stocks')
def recommend_us_sector_stocks(request: Request):
    ticker = request.query_params.get('ticker', '').upper().strip()
    if not ticker:
        return JSONResponse({"ok": False, "error": "ticker 파라미터 필요"}, status_code=400)

    cache_dir = ROOT / 'XGBoost_v2' / 'data' / 'cache' / 'us_sector'
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f'{ticker}.json'
    if cache_file.exists():
        age = (__import__('time').time() - cache_file.stat().st_mtime)
        if age < 3600:
            try:
                return {"ok": True, **json.loads(cache_file.read_text(encoding='utf-8'))}
            except Exception:
                pass

    try:
        import yfinance as yf
        etf = yf.Ticker(ticker)
        hdf = etf.funds_data.top_holdings
        if hdf is None or hdf.empty:
            return {"ok": True, "stocks": [], "count": 0}

        symbols = hdf.index.tolist()[:20]
        raw = yf.download(symbols, period='5d', auto_adjust=True, progress=False)
        close = raw['Close'] if 'Close' in raw.columns else raw

        if hasattr(close, 'name'):
            close = close.to_frame(name=symbols[0])

        stocks = []
        for sym in symbols:
            try:
                s = close[sym].dropna()
                if len(s) < 2:
                    continue
                price = float(s.iloc[-1])
                chg   = (s.iloc[-1] - s.iloc[-2]) / abs(s.iloc[-2]) * 100
                stocks.append({
                    "name":       sym,
                    "code":       sym,
                    "price":      round(price, 2),
                    "change_pct": f"{chg:+.2f}%",
                    "change_dir": "up" if chg > 0.01 else ("down" if chg < -0.01 else "flat"),
                    "ai_pick":    False,
                })
            except Exception:
                pass

        payload = {"stocks": stocks, "count": len(stocks)}
        try:
            cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        return {"ok": True, **payload}
    except Exception as e:
        logger.error(f"[us_sector_stocks] ticker={ticker}: {e}")
        logger.error(f'[recommend] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'}, status_code=500)
