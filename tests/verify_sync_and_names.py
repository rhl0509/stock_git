# -*- coding: utf-8 -*-
"""
검증 스크립트 — 두 가지 수정 사항을 실제 DB/코드 경로로 확인한다.

  1) 월별 성과 ← 키움 동기화: 키움 클라이언트를 목(mock)으로 대체하고
     do_kiwoom_sync 를 호출 → '어제' 매도가 stock_transactions 에 들어오고
     compute_monthly_perf 가 그 달 실현손익을 집계하는지 확인.
     (이전 버그: 당일만 동기화 → 어제 매도 누락)

  2) AI 추천 종목명/코드 일치: _override_names 가 코드에 맞는 권위 종목명(kr_stocks)으로
     교정하는지, recommend_json() 결과가 DB와 일치하는지 확인.

실행: d:/expense_tracker/.venv64/Scripts/python.exe -m tests.verify_sync_and_names
"""
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

TEST_UID = 990277  # 실DB 충돌 방지용 합성 member_id

# 소유자 게이트: do_kiwoom_sync 는 is_owner_user_no(user_no) 로 지정 소유자만 허용한다
# (자동 탐지 제거·fail-closed 하드닝 이후). 이 검증은 합성 유저로 sync 를 호출하므로
# TEST_UID 를 이번 프로세스의 지정 소유자로 설정한다. get_owner_user_no() 는 매 호출 시
# env 를 읽으므로 import 전에 setdefault 해두면 충분하다.
os.environ.setdefault('OWNER_USER_NO', str(TEST_UID))


def _clean(conn, uid):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM stock_transactions WHERE member_id=%s", (uid,))
        cur.execute("DELETE FROM stock_holdings    WHERE member_id=%s", (uid,))
    conn.commit()


def test_kiwoom_sync_to_monthly_perf():
    from database.db_connection import get_db_connection
    import routes.stock_holdings as sh
    from routes.portfolio_perf import compute_monthly_perf

    now = datetime.now()
    ymd = lambda d: d.strftime('%Y%m%d')
    buy_day  = now - timedelta(days=2)   # 이틀 전 매수
    sell_day = now - timedelta(days=1)   # 어제 매도 (이전 버그에선 누락되던 케이스)
    sell_ym  = sell_day.strftime('%Y-%m')

    # ── 키움 클라이언트 목 주입 ──
    # 동기화 원천이 opw00015(기간체결) → opt10073(실현손익)으로 바뀌었으므로
    # get_realized_pnl 을 목으로 주입한다. (opw00015는 빈 값으로 두어 폴백 경로 검증)
    k = sh.kiwoom
    orig = {n: getattr(k, n) for n in
            ('get_login_state', 'get_account_full', 'get_realized_pnl', 'get_period_trades')}
    k.get_login_state = lambda: 1
    k.get_account_full = lambda: {
        'holdings': [{'code': '005930', 'name': '삼성전자', 'quantity': 10, 'avg_price': 70000}],
        'deposit': 5_000_000,
    }
    captured = {}
    def fake_realized(date_from, date_to):
        captured['from'], captured['to'] = date_from, date_to
        # 어제 매도 1건: 매입 70000 → 매도 80000, 10주 = 실현손익 100,000
        return {'total_pnl': 100000, 'stocks': [
            {'code': '005930', 'name': '삼성전자', 'pnl': 100000,
             'date': ymd(sell_day), 'quantity': 10,
             'buy_price': 70000, 'sell_price': 80000},
        ]}
    k.get_realized_pnl = fake_realized
    k.get_period_trades = lambda f, t: []   # opw00015는 비어있음(실제 계좌 재현)

    conn = get_db_connection()
    try:
        _clean(conn, TEST_UID)
        result = sh.do_kiwoom_sync(TEST_UID)
        assert result['ok'] is True, result
        assert result['count'] == 1, f"보유종목 동기화 수 {result['count']}"
        assert result['trade_synced'] == 1, f"매도 동기화 수 {result['trade_synced']}"
        assert result['deposit'] == 5_000_000

        # 동기화 조회 기간이 '당일'이 아니라 최근 N일로 넓어졌는지
        span = (datetime.strptime(captured['to'], '%Y%m%d')
                - datetime.strptime(captured['from'], '%Y%m%d')).days
        assert span >= 7, f"조회기간이 너무 좁음: {captured} (당일만 조회하던 버그?)"

        # 어제 매도가 실제 DB에 들어왔는가
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type, quantity, price FROM stock_transactions "
                "WHERE member_id=%s AND DATE(traded_at)=%s",
                (TEST_UID, sell_day.strftime('%Y-%m-%d')))
            rows = cur.fetchall()
        assert any(r['type'] == 'sell' and r['quantity'] == 10 and r['price'] == 80000
                   for r in rows), f"어제 매도 누락: {rows}"

        # 월별 성과가 그 달 실현손익을 집계하는가 (FIFO: (80000-70000)*10 = 100000)
        perf = compute_monthly_perf(TEST_UID, with_benchmark=False)
        month = next((m for m in perf['monthly'] if m['ym'] == sell_ym), None)
        assert month is not None, f"{sell_ym} 월 데이터 없음: {perf['monthly']}"
        assert month['pnl'] == 100000, f"실현손익 {month['pnl']} != 100000"
        assert perf['summary']['total_pnl'] == 100000
        print(f"  [1] OK — 어제({sell_day:%m/%d}) 매도 동기화→월별성과 반영: "
              f"{sell_ym} 실현손익 {month['pnl']:,}원, 조회기간 {span}일")
    finally:
        for n, fn in orig.items():
            setattr(k, n, fn)
        _clean(conn, TEST_UID)
        conn.close()


def test_recommend_name_override():
    from routes.recommend import _override_names, recommend_json
    from database.db_connection import get_db_connection

    # 코드와 불일치하던 대표 케이스들 (JSON엔 틀린 이름이 박혀 있었음)
    wrong = [
        {'code': '096530', 'name': 'SK바이오팜'},   # 실제 씨젠
        {'code': '000670', 'name': 'DB손해보험'},   # 실제 영풍
        {'code': '068760', 'name': '셀트리온헬스케어'},  # 실제 셀트리온제약
    ]
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT code,name FROM kr_stocks WHERE code IN ('096530','000670','068760')")
        dbmap = {r['code']: r['name'] for r in cur.fetchall()}
    conn.close()

    _override_names(wrong)
    for it in wrong:
        assert it['name'] == dbmap[it['code']], \
            f"{it['code']} 교정 실패: {it['name']} != {dbmap[it['code']]}"
    print(f"  [2a] OK — 종목명 교정: 096530→{dbmap['096530']}, "
          f"000670→{dbmap['000670']}, 068760→{dbmap['068760']}")

    # 실제 서빙 경로(recommend_json)의 모든 항목이 DB 이름과 일치하는지.
    # recommend_json 은 이제 AI 추천 데이 패스(_pass_gate)로 보호되므로, 종목명 교정
    # 로직만 검증하기 위해 이 검증 동안에는 게이트를 우회한다.
    import routes.recommend as _rec
    _orig_gate = _rec._pass_gate
    _rec._pass_gate = lambda request=None: None
    try:
        res = recommend_json(None)
    finally:
        _rec._pass_gate = _orig_gate
    if isinstance(res, dict) and res.get('ok'):
        all_codes = set()
        for sec in ('triple', 'daily', 'short', 'swing'):
            for it in res.get(sec, []) or []:
                all_codes.add(it['code'])
        conn = get_db_connection()
        with conn.cursor() as cur:
            ph = ','.join(['%s'] * len(all_codes))
            cur.execute(f"SELECT code,name FROM kr_stocks WHERE code IN ({ph})", list(all_codes))
            dbmap = {r['code']: r['name'] for r in cur.fetchall()}
        conn.close()
        bad = []
        for sec in ('triple', 'daily', 'short', 'swing'):
            for it in res.get(sec, []) or []:
                exp = dbmap.get(it['code'])
                if exp and it['name'] != exp:
                    bad.append((it['code'], it['name'], exp))
        assert not bad, f"recommend_json 종목명 불일치 잔존: {bad}"
        print(f"  [2b] OK — recommend_json {len(all_codes)}종목 전부 DB 종목명과 일치")
    else:
        print("  [2b] SKIP — daily_recommend.json 없음/오류")


if __name__ == '__main__':
    print("검증 시작")
    test_kiwoom_sync_to_monthly_perf()
    test_recommend_name_override()
    print("전체 통과 ✅")
