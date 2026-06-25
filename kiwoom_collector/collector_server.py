"""
kiwoom_collector/collector_server.py
32비트 Python 전용 — 키움 OpenAPI COM 래핑 Flask 서버
메인(64비트) 서버가 HTTP로 이 서버에 요청을 보냅니다.
"""
import sys, os, json, threading, time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 프로젝트 루트를 path에 추가하여 kiwoom_worker를 import 할 수 있게 함
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request as flask_request
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False   # 한글을 \uXXXX 이스케이프 없이 UTF-8로 직렬화

# ── kiwoom_worker의 싱글톤 인스턴스 import ──
from kiwoom_worker import kiwoom, get_market_session


# ══════════════════════════════════════════════════════
# ── 키움 API 직렬화 + Rate Limiting ──
# ── 키움 COM 객체는 단일 스레드 전용이므로
#    동시 요청이 들어와도 순차 처리되어야 함
# ══════════════════════════════════════════════════════

_api_lock      = threading.Lock()
_last_call_time = [0.0]
_MIN_INTERVAL  = 0.25   # 최대 4 req/s (키움 권장 5건/s 이하)


def _kiwoom(func):
    """모든 키움 API 호출을 이 함수로 래핑 — 직렬화 + 호출 간격 보장."""
    with _api_lock:
        gap = time.time() - _last_call_time[0]
        if gap < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - gap)
        try:
            return func()
        finally:
            _last_call_time[0] = time.time()


# ══════════════════════════════════════════════════════
# ── 헬스체크 ──
# ══════════════════════════════════════════════════════

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "bit": 32})


# ══════════════════════════════════════════════════════
# ── 로그인 / 상태 ──
# ══════════════════════════════════════════════════════

@app.route('/login', methods=['POST'])
def login():
    try:
        result = _kiwoom(lambda: kiwoom.login(timeout=60))
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "err_code": None, "msg": str(e)}), 500


@app.route('/status', methods=['GET'])
def status():
    try:
        # GetConnectState()는 TR이 아닌 단순 COM 상태 조회 — lock 불필요
        state = kiwoom.get_login_state()
        return jsonify({"connected": state == 1, "state": state})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


@app.route('/session', methods=['GET'])
def market_session():
    # get_market_session()은 시각 계산만 하므로 lock 불필요
    return jsonify(get_market_session())


# ══════════════════════════════════════════════════════
# ── 현재가 / 호가 / 종목 정보 ──
# ══════════════════════════════════════════════════════

@app.route('/price/<code>', methods=['GET'])
def price(code):
    try:
        data = _kiwoom(lambda: kiwoom.get_stock_price(code))
        if data:
            return jsonify(data)
        return jsonify({"error": "데이터 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/nxt/price/<code>', methods=['GET'])
def nxt_price(code):
    try:
        data = _kiwoom(lambda: kiwoom.get_nxt_price(code))
        if data:
            return jsonify(data)
        return jsonify({"error": "데이터 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/best/price/<code>', methods=['GET'])
def best_price(code):
    try:
        data = _kiwoom(lambda: kiwoom.get_best_price(code))
        if data:
            return jsonify(data)
        return jsonify({"error": "데이터 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/info/<code>', methods=['GET'])
def stock_info(code):
    try:
        data = _kiwoom(lambda: kiwoom.get_stock_info(code))
        if data:
            return jsonify(data)
        return jsonify({"error": "데이터 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/prices', methods=['POST'])
def multi_price():
    codes = (flask_request.get_json() or {}).get('codes', [])

    def _fetch_all():
        results = {}
        for c in codes:
            try:
                data = kiwoom.get_stock_price(c)
                if data:
                    results[c] = data
                time.sleep(_MIN_INTERVAL)
            except Exception:
                pass
        return results

    return jsonify(_kiwoom(_fetch_all))


# ══════════════════════════════════════════════════════
# ── OHLCV (일봉) ──
# ══════════════════════════════════════════════════════

@app.route('/ohlcv/<code>', methods=['GET'])
def ohlcv(code):
    count = flask_request.args.get('count', 80, type=int)
    try:
        df = _kiwoom(lambda: kiwoom.get_ohlcv(code, count=count))
        if df is not None and not df.empty:
            return jsonify(json.loads(df.to_json(orient='records', date_format='iso')))
        return jsonify({"error": "데이터 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# ── 투자자 동향 ──
# ══════════════════════════════════════════════════════

@app.route('/investor/<code>', methods=['GET'])
def investor_trend(code):
    inv_type = flask_request.args.get('type', '외국인')
    try:
        data = _kiwoom(lambda: kiwoom.get_investor_trend(code, investor_type=inv_type))
        if data:
            return jsonify(data)
        return jsonify({"error": "데이터 없음"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# ── 선물 시세 (KOSPI200 선물 선행신호) ──
# ══════════════════════════════════════════════════════

@app.route('/futures/price', methods=['GET'])
def futures_price():
    """KOSPI200 선물 현재가·등락율. code 미지정 시 env(KOSPI200_FUT_CODE)→최근월물 자동."""
    code = flask_request.args.get('code') or os.getenv('KOSPI200_FUT_CODE', '')
    try:
        if not code:
            code = _kiwoom(lambda: kiwoom.get_kospi200_front_code()) or ''
        if not code:
            return jsonify({"error": "선물 코드 없음"}), 404
        data = _kiwoom(lambda: kiwoom.get_futures_price(code))
        if data:
            return jsonify(data)
        return jsonify({"error": "선물 시세 조회 실패", "code": code}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/futures/code', methods=['GET'])
def futures_code():
    """KOSPI200 선물 최근월물 코드 조회(설정/검증용)."""
    try:
        code = _kiwoom(lambda: kiwoom.get_kospi200_front_code())
        return jsonify({"code": code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# ── 조건검색 ──
# ══════════════════════════════════════════════════════

@app.route('/conditions', methods=['GET'])
def conditions():
    try:
        data = _kiwoom(lambda: kiwoom.load_condition_list())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/condition/run', methods=['POST'])
def condition_run():
    body = flask_request.get_json() or {}
    name = body.get('name', '')
    try:
        result = _kiwoom(lambda: kiwoom.run_condition(name))
        return jsonify({"stocks": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# ── 테마 ──
# ══════════════════════════════════════════════════════

@app.route('/themes', methods=['GET'])
def themes():
    sort_type = flask_request.args.get('sort', 0, type=int)
    try:
        data = _kiwoom(lambda: kiwoom.get_theme_list(sort=sort_type))
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/theme/stocks', methods=['POST'])
def theme_stocks():
    body = flask_request.get_json() or {}
    theme_code = body.get('theme_code', '')
    try:
        data = _kiwoom(lambda: kiwoom.get_theme_stocks(theme_code))
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/theme-index/build', methods=['POST'])
def theme_index_build():
    try:
        index = _kiwoom(lambda: kiwoom.build_theme_index(force=True))
        return jsonify({"count": len(index)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/theme-index/status', methods=['GET'])
def theme_index_status():
    cache = kiwoom._theme_index_cache
    return jsonify({
        "built": cache is not None,
        "code_count": len(cache) if cache else 0,
    })


@app.route('/related-stocks', methods=['POST'])
def related_stocks():
    body  = flask_request.get_json() or {}
    code  = body.get('code', '').strip().lstrip('A')
    force = body.get('force', False)
    if not code:
        return jsonify({"error": "종목코드 필요"}), 400

    if force or kiwoom._theme_index_cache is None:
        kiwoom.build_theme_index(force=True)

    index = kiwoom._theme_index_cache
    if not index:
        return jsonify({"error": "테마 인덱스 빌드 실패"}), 500

    matched = index.get(code, [])
    if not matched:
        return jsonify({
            "code": code, "themes": [],
            "related_codes": [], "related_count": 0,
            "message": f"종목코드 {code}가 속한 테마를 찾을 수 없습니다.",
        })

    related_set = set()
    themes_out  = []
    for t in matched:
        theme_codes = [
            c for c, themes in index.items()
            if any(th['theme_code'] == t['theme_code'] for th in themes)
            and c != code
        ]
        related_set.update(theme_codes)
        themes_out.append({
            "theme_code":  t['theme_code'],
            "theme_name":  t['theme_name'],
            "rate":        t.get('rate', 0),
            "stock_count": len(theme_codes) + 1,
        })

    related_list = list(related_set)
    return jsonify({
        "code": code, "themes": themes_out,
        "related_codes": related_list,
        "related_count": len(related_list),
    })


# ══════════════════════════════════════════════════════
# ── 계좌 ──
# ══════════════════════════════════════════════════════

@app.route('/account/no', methods=['GET'])
def account_no():
    try:
        acct = _kiwoom(lambda: kiwoom.get_account_no())
        return jsonify({"account_no": acct})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/account/holdings', methods=['GET'])
def account_holdings():
    try:
        holdings = _kiwoom(lambda: kiwoom.get_account_holdings())
        deposit  = kiwoom.get_deposit()   # opw00018 캐시 (holdings 조회 부산물)
        return jsonify({"holdings": holdings or [], "deposit": deposit})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/account/deposit', methods=['GET'])
def account_deposit():
    try:
        deposit = kiwoom.get_deposit()
        if deposit is None:
            return jsonify({"error": "예수금 없음 — 보유종목 조회를 먼저 실행하세요"}), 404
        return jsonify({"deposit": deposit})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/account/trades', methods=['GET'])
def account_trades():
    """당일 체결현황 조회 (opw00007) — 장중에만 유효"""
    try:
        trades = _kiwoom(lambda: kiwoom.get_daily_trades())
        return jsonify({"trades": trades or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/account/period-trades', methods=['GET'])
def account_period_trades():
    """기간별 체결 내역 조회 (opw00015). ?from=YYYYMMDD&to=YYYYMMDD"""
    date_from = flask_request.args.get('from', '')
    date_to   = flask_request.args.get('to',   '')
    if not date_from or not date_to:
        return jsonify({"error": "from/to 파라미터 필요 (YYYYMMDD)"}), 400
    try:
        trades = _kiwoom(lambda: kiwoom.get_period_trades(date_from, date_to))
        return jsonify({"trades": trades or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/account/realized-pnl', methods=['GET'])
def account_realized_pnl():
    """계좌별 실현손익 조회 (opt10073). ?from=YYYYMMDD&to=YYYYMMDD"""
    date_from = flask_request.args.get('from', '')
    date_to   = flask_request.args.get('to',   '')
    if not date_from or not date_to:
        return jsonify({"error": "from/to 파라미터 필요 (YYYYMMDD)"}), 400
    try:
        data = _kiwoom(lambda: kiwoom.get_realized_pnl(date_from, date_to))
        if data is None:
            return jsonify({"error": "실현손익 조회 실패"}), 500
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════
# ── 메인 ──
# ══════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 50)
    print("  키움 32비트 콜렉터 서버 시작 (포트 5100)")
    print("=" * 50)
    app.run(host='127.0.0.1', port=5100, debug=False, use_reloader=False)
