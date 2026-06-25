"""routes/workflows.py — n8n식 노코드 워크플로 엔진 (추가 전용, 기존 코드 미수정).

워크플로 = 트리거 + 순서대로 실행되는 액션 목록(코드 없이 조합).
액션은 기존 기능(키움 동기화·월별성과·추천·LLM 요약·카카오 발송)을 '호출만' 한다.
실행할 때마다 단계별 결과를 workflow_runs 에 기록 → 시각적 관찰(관측가능성).
"""
import json
import logging
from datetime import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from database.db_connection import get_db_connection
from routes.utils import api_require_login, get_user_no

router = APIRouter()
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent


def _require_kiwoom():
    """키움 미접속이면 RuntimeError. 현재가/실현손익 액션의 조용한 평단가 폴백을
    명시적 실패로 전환해 예약 실행 실패 알림이 발동되도록 한다."""
    from kiwoom_client import kiwoom
    if kiwoom.get_login_state() != 1:
        raise RuntimeError('키움 미접속 — 32비트 콜렉터/로그인 상태 확인 필요')


# ══════════════════════════════════════════════════════════════════
# 액션 레지스트리 — 각 액션은 기존 기능을 래핑만 한다.
#   fn(ctx, params) -> str(로그 한 줄).  ctx['text'] 에 메시지를 누적.
# ══════════════════════════════════════════════════════════════════

def _act_kiwoom_sync(ctx, params):
    from routes.stock_holdings import do_kiwoom_sync
    r = do_kiwoom_sync(ctx['member_id'])
    if not r.get('ok'):
        raise RuntimeError(r.get('error') or '키움 동기화 실패')
    line = f"🔄 키움 동기화: 보유 {r['count']}종목 · 매도 {r['trade_synced']}건"
    ctx['text'] += line + "\n"
    return line


def _act_portfolio_perf(ctx, params):
    from routes.portfolio_perf import compute_monthly_perf
    perf = compute_monthly_perf(ctx['member_id'], with_benchmark=False)
    months = perf.get('monthly') or []
    if not months:
        line = "📊 월별성과: 데이터 없음"
    else:
        last = months[-1]
        s = perf.get('summary', {})
        line = (f"📊 {last['ym']} 실현손익 {last['pnl']:+,}원 "
                f"({last['ret_pct']}%) · 누적 {s.get('total_pnl', 0):+,}원")
    ctx['text'] += line + "\n"
    return line


def _act_recommend_top(ctx, params):
    n = max(1, min(int(params.get('n', 3)), 10))
    cat = params.get('category', 'daily')
    if cat not in ('daily', 'short', 'swing'):
        cat = 'daily'
    path = ROOT / 'XGBoost_v2' / 'model' / 'daily_recommend.json'
    if not path.exists():
        raise RuntimeError('추천 데이터(daily_recommend.json) 없음')
    data = json.loads(path.read_text(encoding='utf-8'))
    picks = (data.get(cat) or [])[:n]
    try:
        from routes.recommend import _override_names   # 종목명 DB 교정 재사용
        _override_names(picks)
    except Exception:
        pass
    lines = [f"🔥 추천 {cat.upper()} TOP{len(picks)} (기준 {data.get('base_date', '')})"]
    for p in picks:
        lines.append(f"  · {p.get('name')}({p.get('code')}) "
                     f"신뢰도 {float(p.get('confidence', 0)) * 100:.0f}%")
    block = "\n".join(lines)
    ctx['text'] += block + "\n"
    return f"추천 {len(picks)}개 ({cat})"


def _act_ai_summarize(ctx, params):
    from agent.llm_client import generate
    src = (ctx.get('text') or '').strip()
    if not src:
        return "AI 요약 건너뜀(내용 없음)"
    instr = params.get('instruction') or "아래 데이터를 투자자에게 보낼 한국어 브리핑으로 간결히 요약·논평해줘. 핵심만, 6줄 이내."
    out = generate(f"{instr}\n\n---\n{src}",
                   system="너는 한국 주식 투자 보조 AI다. 과장 없이 핵심만 간결하게.",
                   temperature=0.3, max_tokens=600)
    if out and out.strip():
        ctx['summary'] = out.strip()
        ctx['text'] = out.strip()          # 메시지를 AI 서술로 대체(원문은 data에 보존)
        ctx['raw'] = src
        return f"🤖 AI 요약 생성 ({len(out)}자)"
    return "AI 요약 실패(빈 응답)"


def _act_holdings_detail(ctx, params):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, code, quantity, avg_price FROM stock_holdings "
                "WHERE member_id=%s ORDER BY quantity*avg_price DESC", (ctx['member_id'],))
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        ctx['text'] += "보유 종목 없음\n"
        return "보유 종목 없음"
    lines = ["📌 보유 종목"]
    for r in rows:
        qty = int(r['quantity'] or 0)
        ap = int(r['avg_price'] or 0)
        lines.append(f"  · {r['name']} {qty:,}주 · 평단 {ap:,}원")
    ctx['text'] += "\n".join(lines) + "\n"
    return f"보유 {len(rows)}종목 상세"


def _act_realized_pnl(ctx, params):
    from datetime import datetime as _dt, timedelta as _td
    from kiwoom_client import kiwoom
    _require_kiwoom()
    period = (params.get('period') or 'today').lower()
    now = _dt.now()
    if period == 'week':
        start = now - _td(days=now.weekday())   # 이번 주 월요일
        label = '이번 주'
    elif period == 'month':
        start = now.replace(day=1)
        label = '이번 달'
    else:
        start = now
        label = '오늘'
    pnl = kiwoom.get_realized_pnl(start.strftime('%Y%m%d'), now.strftime('%Y%m%d')) or {}
    stocks = [s for s in (pnl.get('stocks') or []) if s.get('pnl')]
    total = pnl.get('total_pnl', 0)
    if stocks:
        sign = '+' if total >= 0 else ''
        lines = [f"💹 {label} 실현손익: {sign}{total:,}원 ({len(stocks)}종목 매도)"]
        for s in sorted(stocks, key=lambda x: x['pnl'], reverse=True):
            sg = '+' if s['pnl'] >= 0 else ''
            lines.append(f"  · {s['name']} {sg}{s['pnl']:,}원")
        ctx['text'] += "\n".join(lines) + "\n"
        return f"{label} 실현손익 {sign}{total:,}원"
    ctx['text'] += f"💹 {label} 실현손익: 매도 없음\n"
    return f"{label} 실현손익(매도 없음)"


def _act_holdings_valuation(ctx, params):
    from kiwoom_client import kiwoom
    _require_kiwoom()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, code, quantity, avg_price FROM stock_holdings "
                "WHERE member_id=%s ORDER BY quantity*avg_price DESC", (ctx['member_id'],))
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        ctx['text'] += "보유 종목 없음\n"
        return "보유 종목 없음"
    total_invest = total_eval = 0
    items = []
    for r in rows:
        qty = int(r['quantity'] or 0)
        ap = int(r['avg_price'] or 0)
        pd = kiwoom.get_best_price(r['code']) or {}
        cur_price = int(pd.get('price') or 0) or ap   # 미접속/실패 시 평단가 폴백(평가손익 0)
        invest = ap * qty
        evalamt = cur_price * qty
        profit = evalamt - invest
        ret = (profit / invest * 100) if invest else 0
        total_invest += invest
        total_eval += evalamt
        items.append((r['name'], profit, ret))
    total_profit = total_eval - total_invest
    total_ret = (total_profit / total_invest * 100) if total_invest else 0
    sign = '+' if total_profit >= 0 else ''
    lines = [f"📈 평가손익: {sign}{total_profit:,}원 ({sign}{total_ret:.2f}%) · 평가액 {total_eval:,}원"]
    for name, profit, ret in sorted(items, key=lambda x: x[1], reverse=True):
        sg = '+' if profit >= 0 else ''
        lines.append(f"  · {name} {sg}{profit:,}원 ({sg}{ret:.1f}%)")
    ctx['text'] += "\n".join(lines) + "\n"
    return f"평가손익 {sign}{total_profit:,}원"


def _act_notify_kakao(ctx, params):
    from notify.send import send_message_to_self
    text = (ctx.get('text') or '').strip()
    if params.get('prefix'):
        text = f"{params['prefix']}\n{text}"
    if not text:
        raise RuntimeError('발송할 메시지가 비어 있음')
    ok = send_message_to_self(text, ai_generated=bool(ctx.get('summary')))
    if not ok:
        raise RuntimeError('카카오 발송 실패(토큰/네트워크 확인)')
    return f"💬 카카오 발송 ({len(text)}자)"


def _act_notify_telegram(ctx, params):
    from notify.telegram import send_telegram
    text = (ctx.get('text') or '').strip()
    if params.get('prefix'):
        text = f"{params['prefix']}\n{text}"
    if not text:
        raise RuntimeError('발송할 메시지가 비어 있음')
    ok = send_telegram(text)
    if not ok:
        raise RuntimeError('텔레그램 발송 실패(토큰/chat_id 확인)')
    return f"📨 텔레그램 발송 ({len(text)}자)"


# 키: (라벨, 설명, 함수, 파라미터 스키마[프론트 폼 생성용])
ACTIONS = {
    'kiwoom_sync':    ("키움 계좌 동기화", "보유종목·실현손익을 키움에서 동기화", _act_kiwoom_sync, []),
    'portfolio_perf': ("월별 성과 집계",   "최근 월 실현손익/누적 손익 요약",     _act_portfolio_perf, []),
    'holdings_detail': ("보유 종목 상세",   "현재 보유 종목의 수량·평단가를 메시지에 추가",
                       _act_holdings_detail, []),
    'holdings_valuation': ("보유 평가손익", "보유종목 현재가 기준 평가손익(±금액/%)을 종목별로 메시지에 추가",
                       _act_holdings_valuation, []),
    'realized_pnl':   ("실현손익(기간)",    "매도로 확정된 실현손익을 기간별(오늘/이번주/이번달)로 메시지에 추가",
                       _act_realized_pnl,
                       [{'key': 'period', 'label': '기간', 'type': 'select',
                         'options': ['today', 'week', 'month'], 'default': 'today'}]),
    'recommend_top':  ("AI 추천 TOP",      "오늘의 추천 상위 N개를 메시지에 추가",
                       _act_recommend_top,
                       [{'key': 'category', 'label': '카테고리', 'type': 'select',
                         'options': ['daily', 'short', 'swing'], 'default': 'daily'},
                        {'key': 'n', 'label': '개수', 'type': 'number', 'default': 3}]),
    'ai_summarize':   ("AI 요약/논평",     "지금까지 모인 내용을 로컬 LLM(Ollama)으로 서술 요약",
                       _act_ai_summarize,
                       [{'key': 'instruction', 'label': '지시문(선택)', 'type': 'text', 'default': ''}]),
    'notify_kakao':   ("카카오 발송",      "현재 메시지를 카카오톡 '나에게 보내기'로 전송",
                       _act_notify_kakao,
                       [{'key': 'prefix', 'label': '머리말(선택)', 'type': 'text', 'default': ''}]),
    'notify_telegram': ("텔레그램 발송",    "현재 메시지를 텔레그램 봇으로 전송",
                       _act_notify_telegram,
                       [{'key': 'prefix', 'label': '머리말(선택)', 'type': 'text', 'default': ''}]),
}


# ══════════════════════════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════════════════════════

def _ensure_tables():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    member_id  INT          NOT NULL,
                    name       VARCHAR(100) NOT NULL,
                    steps      TEXT         NOT NULL,
                    enabled    TINYINT(1)   NOT NULL DEFAULT 1,
                    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX(member_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    workflow_id INT          NOT NULL,
                    status      VARCHAR(10)  NOT NULL DEFAULT 'ok',
                    `trigger`   VARCHAR(20)  NOT NULL DEFAULT 'manual',
                    log         TEXT         NOT NULL,
                    message     TEXT,
                    started_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    ended_at    DATETIME,
                    INDEX(workflow_id)
                )
            """)
        conn.commit()
        # schedule 컬럼 마이그레이션 (이미 있으면 무시)
        try:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE workflows ADD COLUMN schedule VARCHAR(120) DEFAULT NULL")
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


_tables_ready = False


def _ready():
    global _tables_ready
    if not _tables_ready:
        _ensure_tables()
        _tables_ready = True


# ══════════════════════════════════════════════════════════════════
# 실행 엔진
# ══════════════════════════════════════════════════════════════════

def _alert_failure(wf: dict, log: list, started=None):
    """예약 실행이 실패하면(아무도 안 보고 있는 상황) 텔레그램으로 경고를 쏜다.
    수동 실행은 UI에 즉시 결과가 뜨므로 알리지 않는다."""
    try:
        from notify.telegram import send_telegram
        failed = next((l for l in log if not l.get('ok')), None)
        if failed:
            step_txt = f"{failed.get('step')}. {failed.get('label') or failed.get('action')}"
            reason = failed.get('detail') or '알 수 없음'
        else:
            step_txt, reason = '?', '알 수 없음'
        when = (started or _dt.now()).strftime('%Y-%m-%d %H:%M:%S')
        msg = (f"⚠️ 워크플로 실패: '{wf.get('name')}' (ID #{wf.get('id')})\n"
               f"실패 단계: {step_txt}\n"
               f"사유: {reason}\n"
               f"실행 시각: {when}")
        send_telegram(msg)
    except Exception as e:
        logger.error(f'[workflow] 실패 알림 발송 오류: {e}')


def run_workflow(wf: dict, member_id: int, trigger: str = 'manual') -> dict:
    """워크플로 단계를 순서대로 실행하고 workflow_runs 에 기록."""
    try:
        steps = json.loads(wf['steps']) if isinstance(wf['steps'], str) else (wf['steps'] or [])
    except Exception:
        steps = []
    ctx = {'member_id': member_id, 'text': '', 'data': {}}
    log, status = [], 'ok'
    started = _dt.now()

    for idx, step in enumerate(steps):
        akey = step.get('action')
        meta = ACTIONS.get(akey)
        if not meta:
            log.append({'step': idx + 1, 'action': akey, 'ok': False, 'detail': '알 수 없는 액션'})
            status = 'error'
            break
        try:
            detail = meta[2](ctx, step.get('params') or {})
            log.append({'step': idx + 1, 'action': akey, 'label': meta[0], 'ok': True, 'detail': detail})
        except Exception as e:
            logger.warning(f'[workflow] step {idx+1} {akey} 실패: {e}')
            log.append({'step': idx + 1, 'action': akey, 'label': meta[0], 'ok': False, 'detail': str(e)[:200]})
            status = 'error'
            break   # 실패 시 중단(이후 단계 미실행)

    message = (ctx.get('text') or '').strip()[:2000]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workflow_runs (workflow_id, status, `trigger`, log, message, started_at, ended_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (wf['id'], status, trigger, json.dumps(log, ensure_ascii=False), message, started, _dt.now()))
            run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    if status == 'error' and trigger == 'schedule':
        _alert_failure(wf, log, started)
    return {'run_id': run_id, 'status': status, 'log': log, 'message': message}


# ── 스케줄 디스패처 (auto_jobs 가 매분 호출) ──

def _day_matches(days: str, dow: str) -> bool:
    """days: 'daily' | 'mon-fri' | 'weekend' | 'mon,wed,fri' 등.  dow: 'mon'..'sun'."""
    days = (days or 'daily').strip().lower()
    if days in ('daily', 'everyday', ''):
        return True
    if days in ('mon-fri', 'weekday', 'weekdays'):
        return dow in ('mon', 'tue', 'wed', 'thu', 'fri')
    if days in ('weekend', 'sat-sun'):
        return dow in ('sat', 'sun')
    return dow in {d.strip() for d in days.split(',')}


def run_scheduled_workflows() -> int:
    """현재 시각(Asia/Seoul)과 일치하는 enabled 워크플로를 실행. 실행 건수 반환.
    auto_jobs 의 매분 디스패처가 호출한다."""
    _ready()
    try:
        from zoneinfo import ZoneInfo
        now = _dt.now(ZoneInfo('Asia/Seoul'))
    except Exception:
        now = _dt.now()
    hhmm = now.strftime('%H:%M')
    dow = now.strftime('%a').lower()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, member_id, name, steps, schedule FROM workflows "
                        "WHERE enabled=1 AND schedule IS NOT NULL AND schedule<>''")
            rows = cur.fetchall()
    finally:
        conn.close()

    ran = 0
    for r in rows:
        try:
            sched = json.loads(r['schedule'])
        except Exception:
            continue
        if not sched or sched.get('enabled') is False:
            continue
        if sched.get('time') != hhmm:
            continue
        if not _day_matches(sched.get('days', 'daily'), dow):
            continue
        try:
            run_workflow(r, r['member_id'], trigger='schedule')
            ran += 1
            logger.info(f"[workflow] 예약 실행: '{r['name']}' (id={r['id']})")
        except Exception as e:
            logger.error(f"[workflow] 예약 실행 실패 (id={r['id']}): {e}")
    return ran


# ══════════════════════════════════════════════════════════════════
# 라우트
# ══════════════════════════════════════════════════════════════════

# 과금 액션 없음(AI 요약은 로컬 Ollama 사용 — 무료). 프론트 과금 배지 표시용.
_PAID_ACTIONS: set[str] = set()

@router.get('/api/workflows/actions', dependencies=[Depends(api_require_login)])
def list_actions():
    return {'actions': [
        {'key': k, 'label': v[0], 'description': v[1], 'params': v[3],
         'paid': k in _PAID_ACTIONS}
        for k, v in ACTIONS.items()
    ]}


@router.get('/api/workflows', dependencies=[Depends(api_require_login)])
def list_workflows(request: Request):
    _ready()
    uid = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, steps, schedule, enabled, updated_at FROM workflows "
                        "WHERE member_id=%s ORDER BY id DESC", (uid,))
            rows = cur.fetchall()
            for r in rows:
                try:
                    r['steps'] = json.loads(r['steps'])
                except Exception:
                    r['steps'] = []
                try:
                    r['schedule'] = json.loads(r['schedule']) if r.get('schedule') else None
                except Exception:
                    r['schedule'] = None
                if hasattr(r.get('updated_at'), 'isoformat'):
                    r['updated_at'] = r['updated_at'].isoformat()
                cur.execute("SELECT status, started_at FROM workflow_runs WHERE workflow_id=%s "
                            "ORDER BY id DESC LIMIT 1", (r['id'],))
                lr = cur.fetchone()
                r['last_status'] = lr['status'] if lr else None
                lra = lr['started_at'] if lr else None
                r['last_run_at'] = lra.isoformat() if hasattr(lra, 'isoformat') else None
        return {'workflows': rows, 'count': len(rows)}
    finally:
        conn.close()


@router.post('/api/workflows', dependencies=[Depends(api_require_login)])
def create_workflow(request: Request, body: dict = Body(default={})):
    _ready()
    uid = get_user_no(request)
    name = (body.get('name') or '').strip()
    steps = body.get('steps') or []
    schedule = body.get('schedule')
    sched_str = json.dumps(schedule, ensure_ascii=False) if schedule else None
    if not name:
        return JSONResponse({'error': '이름이 필요합니다.'}, status_code=400)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO workflows (member_id, name, steps, schedule) VALUES (%s,%s,%s,%s)",
                        (uid, name, json.dumps(steps, ensure_ascii=False), sched_str))
            wid = cur.lastrowid
        conn.commit()
        return {'ok': True, 'id': wid}
    finally:
        conn.close()


@router.put('/api/workflows/{wid}', dependencies=[Depends(api_require_login)])
def update_workflow(wid: int, request: Request, body: dict = Body(default={})):
    _ready()
    uid = get_user_no(request)
    fields, vals = [], []
    if 'name' in body:
        fields.append('name=%s'); vals.append((body.get('name') or '').strip())
    if 'steps' in body:
        fields.append('steps=%s'); vals.append(json.dumps(body.get('steps') or [], ensure_ascii=False))
    if 'enabled' in body:
        fields.append('enabled=%s'); vals.append(1 if body.get('enabled') else 0)
    if 'schedule' in body:
        sch = body.get('schedule')
        fields.append('schedule=%s'); vals.append(json.dumps(sch, ensure_ascii=False) if sch else None)
    if not fields:
        return JSONResponse({'error': '변경할 내용이 없습니다.'}, status_code=400)
    vals += [wid, uid]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE workflows SET {', '.join(fields)} WHERE id=%s AND member_id=%s", vals)
            if cur.rowcount == 0:
                return JSONResponse({'error': '워크플로를 찾을 수 없습니다.'}, status_code=404)
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.delete('/api/workflows/{wid}', dependencies=[Depends(api_require_login)])
def delete_workflow(wid: int, request: Request):
    _ready()
    uid = get_user_no(request)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workflows WHERE id=%s AND member_id=%s", (wid, uid))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


def _load_owned(wid: int, uid: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, steps FROM workflows WHERE id=%s AND member_id=%s", (wid, uid))
            return cur.fetchone()
    finally:
        conn.close()


@router.post('/api/workflows/{wid}/run', dependencies=[Depends(api_require_login)])
def run_now(wid: int, request: Request):
    _ready()
    uid = get_user_no(request)
    wf = _load_owned(wid, uid)
    if not wf:
        return JSONResponse({'error': '워크플로를 찾을 수 없습니다.'}, status_code=404)
    try:
        result = run_workflow(wf, uid, trigger='manual')
        return {'ok': True, **result}
    except Exception as e:
        logger.error(f'[workflow] 실행 오류: {e}', exc_info=True)
        return JSONResponse({'error': '실행 중 서버 오류가 발생했습니다.'}, status_code=500)


@router.get('/api/workflows/{wid}/runs', dependencies=[Depends(api_require_login)])
def list_runs(wid: int, request: Request):
    _ready()
    uid = get_user_no(request)
    if not _load_owned(wid, uid):
        return JSONResponse({'error': '워크플로를 찾을 수 없습니다.'}, status_code=404)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status, `trigger`, log, message, started_at, ended_at "
                        "FROM workflow_runs WHERE workflow_id=%s ORDER BY id DESC LIMIT 20", (wid,))
            rows = cur.fetchall()
            for r in rows:
                try:
                    r['log'] = json.loads(r['log'])
                except Exception:
                    r['log'] = []
                for k in ('started_at', 'ended_at'):
                    if hasattr(r.get(k), 'isoformat'):
                        r[k] = r[k].isoformat()
        return {'runs': rows}
    finally:
        conn.close()
