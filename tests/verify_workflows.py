# -*- coding: utf-8 -*-
"""워크플로 엔진 + 스케줄러 전 구간 검증.

- HTTP 라우트(생성/목록/실행/이력/수정/삭제)를 TestClient로 실제 호출
- 5개 액션 전부 실행(외부 부작용은 목 처리: 키움/LLM/카카오)
- 에러 경로(알 수 없는 액션) 관측가능성 확인
- 스케줄 디스패처가 시각 매칭 시 실행되는지 확인
- 기존 모듈 임포트 회귀 확인
- 테스트 데이터 정리

실행: d:/expense_tracker/.venv64/Scripts/python.exe -m tests.verify_workflows
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

TEST_UID = 990321
PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}")


def main():
    import json
    from datetime import datetime
    import app as appmod
    import routes.workflows as wfmod
    import routes.stock_holdings as sh
    import agent.llm_client as llm
    import notify.send as ns
    from routes.utils import api_require_login
    from database.db_connection import get_db_connection

    # ── 인증 우회 + 외부 부작용 목 ──
    appmod.app.dependency_overrides[api_require_login] = lambda: None
    wfmod.get_user_no = lambda request: TEST_UID
    sh.do_kiwoom_sync = lambda uid: {'ok': True, 'count': 3, 'trade_synced': 14, 'deposit': 1000}
    llm.generate = lambda *a, **k: "🤖 오늘 실현손익 양호, 추천 종목 점검 요망."
    _kakao = {'sent': None}
    def _fake_send(text, **k): _kakao['sent'] = text; return True
    ns.send_message_to_self = _fake_send

    from fastapi.testclient import TestClient
    c = TestClient(appmod.app)

    print("\n[1] 액션 카탈로그")
    r = c.get('/api/workflows/actions'); j = r.json()
    keys = [a['key'] for a in j.get('actions', [])]
    check("HTTP 200", r.status_code == 200)
    check("5개 액션 존재", set(keys) == {'kiwoom_sync','portfolio_perf','recommend_top','ai_summarize','notify_kakao'})

    print("\n[2] 워크플로 생성 (5단계 + 스케줄)")
    now = datetime.now()
    steps = [
        {'action':'kiwoom_sync','params':{}},
        {'action':'portfolio_perf','params':{}},
        {'action':'recommend_top','params':{'category':'daily','n':3}},
        {'action':'ai_summarize','params':{}},
        {'action':'notify_kakao','params':{'prefix':'[자동]'}},
    ]
    r = c.post('/api/workflows', json={'name':'__verify_wf__','steps':steps,
                                       'schedule':{'days':'mon-fri','time':'15:40'}})
    wid = r.json().get('id')
    check("생성 200 + id 반환", r.status_code == 200 and wid)

    print("\n[3] 목록 조회 — 방금 생성분 포함 + 스케줄 직렬화")
    r = c.get('/api/workflows'); wfs = r.json().get('workflows', [])
    mine = next((w for w in wfs if w['id'] == wid), None)
    check("목록에 존재", mine is not None)
    check("steps 5개", mine and len(mine['steps']) == 5)
    check("schedule 객체 복원", mine and isinstance(mine.get('schedule'), dict) and mine['schedule']['time'] == '15:40')

    print("\n[4] 지금 실행 — 5단계 전부 성공 + 메시지 누적")
    r = c.post(f'/api/workflows/{wid}/run'); run = r.json()
    check("실행 200", r.status_code == 200)
    check("status ok", run.get('status') == 'ok')
    check("로그 5단계", len(run.get('log', [])) == 5)
    check("전 단계 성공", all(L['ok'] for L in run.get('log', [])))
    check("카카오 발송 호출됨(머리말 포함)", _kakao['sent'] and _kakao['sent'].startswith('[자동]'))
    check("AI요약이 메시지 본문", 'AI요약' in run.get('message','') or '🤖' in run.get('message',''))

    print("\n[5] 실행 이력 조회")
    r = c.get(f'/api/workflows/{wid}/runs'); runs = r.json().get('runs', [])
    check("이력 1건 이상", len(runs) >= 1)
    check("trigger=manual 기록", runs[0]['trigger'] == 'manual')

    print("\n[6] 수정 (이름/enabled/schedule)")
    r = c.put(f'/api/workflows/{wid}', json={'name':'__verify_wf2__','enabled':True,
                                             'schedule':{'days':'daily','time':'09:00'}})
    check("수정 200", r.status_code == 200 and r.json().get('ok'))
    r = c.get('/api/workflows'); mine = next((w for w in r.json()['workflows'] if w['id']==wid), None)
    check("이름 반영", mine and mine['name'] == '__verify_wf2__')
    check("schedule 변경 반영", mine and mine['schedule']['time'] == '09:00')

    print("\n[7] 에러 경로 — 알 수 없는 액션이면 status=error + 중단")
    rb = c.post('/api/workflows', json={'name':'__verify_bad__','steps':[
        {'action':'portfolio_perf','params':{}}, {'action':'__nope__','params':{}},
        {'action':'notify_kakao','params':{}}]})
    bad_id = rb.json()['id']
    run2 = c.post(f'/api/workflows/{bad_id}/run').json()
    check("status error", run2.get('status') == 'error')
    check("2단계에서 중단(로그 2개)", len(run2.get('log', [])) == 2)
    check("2단계 실패 기록", run2['log'][1]['ok'] is False)

    print("\n[8] 스케줄 디스패처 — 현재 시각 매칭 워크플로 자동 실행")
    try:
        from zoneinfo import ZoneInfo; nowk = datetime.now(ZoneInfo('Asia/Seoul'))
    except Exception: nowk = datetime.now()
    hhmm = nowk.strftime('%H:%M')
    c.put(f'/api/workflows/{wid}', json={'enabled':True,'schedule':{'days':'daily','time':hhmm}})
    before = len(c.get(f'/api/workflows/{wid}/runs').json()['runs'])
    ran = wfmod.run_scheduled_workflows()
    after = len(c.get(f'/api/workflows/{wid}/runs').json()['runs'])
    runs2 = c.get(f'/api/workflows/{wid}/runs').json()['runs']
    check("디스패처 1건 이상 실행", ran >= 1)
    check("이력 증가", after > before)
    check("trigger=schedule 기록", any(rr['trigger']=='schedule' for rr in runs2))

    print("\n[9] 삭제")
    check("삭제 200", c.delete(f'/api/workflows/{wid}').json().get('ok'))
    c.delete(f'/api/workflows/{bad_id}')
    r = c.get('/api/workflows'); ids = [w['id'] for w in r.json()['workflows']]
    check("목록에서 제거됨", wid not in ids and bad_id not in ids)

    print("\n[10] 기존 코드 회귀 — 핵심 모듈/함수 정상")
    import routes.portfolio_perf, routes.recommend, routes.stock_holdings, routes.kr_stocks
    check("portfolio_perf.compute_monthly_perf 존재", hasattr(routes.portfolio_perf,'compute_monthly_perf'))
    check("recommend._override_names 존재", hasattr(routes.recommend,'_override_names'))
    check("app 라우트 수 정상(>=260)", sum(1 for _ in appmod.app.routes) >= 260)

    # ── 정리 (테스트 잔여 데이터 완전 삭제) ──
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM workflows WHERE member_id=%s", (TEST_UID,))
        for row in cur.fetchall():
            cur.execute("DELETE FROM workflow_runs WHERE workflow_id=%s", (row['id'],))
        cur.execute("DELETE FROM workflows WHERE member_id=%s", (TEST_UID,))
    conn.commit(); conn.close()
    appmod.app.dependency_overrides.clear()
    print("\n[cleanup] 테스트 데이터 삭제 완료")


if __name__ == '__main__':
    print("=" * 50)
    main()
    print("=" * 50)
    print(f"통과 {len(PASS)} / 실패 {len(FAIL)}")
    if FAIL:
        print("실패 항목:", FAIL); sys.exit(1)
    print("전체 통과 ✅")
