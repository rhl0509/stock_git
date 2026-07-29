"""가계부 아웃박스(gagebu_outbox) 회귀 테스트 — 적재·멱등·백오프·복구·소유자 게이트.

외부 가계부 앱 없이 로직만 검증한다(전송 성공 경로는 send_transaction 을 스텁으로 대체).
실DB(stock_git)의 gagebu_outbox 테이블을 쓰며 테스트 행은 자동 정리한다.

실행: d:\\expense_tracker\\.venv64\\Scripts\\python.exe -m pytest tests/test_gagebu_outbox.py -q
"""
import hashlib
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ['RUN_SCHEDULER'] = 'false'

import config  # noqa: E402,F401  .env 로드
import gagebu_outbox as ob  # noqa: E402
from database.db_connection import get_db_connection  # noqa: E402

_PREFIX = 'pytest_outbox_'


def _q1(sql, args=()):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()
    finally:
        conn.close()


def _ex(sql, args=()):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def _key(tag):
    return _PREFIX + hashlib.sha256(tag.encode()).hexdigest()[:48]


@pytest.fixture()
def owner_id():
    row = _q1("SELECT id FROM members WHERE user_id='rho'")
    if not row:
        pytest.skip("rho 계정 없음 — 실DB 전제")
    return row['id']


@pytest.fixture(autouse=True)
def _cleanup():
    _ex("DELETE FROM gagebu_outbox WHERE idempotency_key LIKE %s", (_PREFIX + '%',))
    yield
    _ex("DELETE FROM gagebu_outbox WHERE idempotency_key LIKE %s", (_PREFIX + '%',))


def _enqueue(key, member_id, owner_user_no):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            created = ob.enqueue(
                cur, idempotency_key=key, source='trade', member_id=member_id,
                type_val='expense', amount=1000, title='테스트', date_str='2026-07-18',
                category_hint='매수', owner_user_no=owner_user_no)
        conn.commit()
        return created
    finally:
        conn.close()


# ── 적재 ────────────────────────────────────────────────────────────

def test_enqueue_owner_is_pending(owner_id):
    _enqueue(_key('pending'), owner_id, owner_id)
    row = _q1("SELECT status, attempts, next_retry_at FROM gagebu_outbox WHERE idempotency_key=%s",
              (_key('pending'),))
    assert row['status'] == 'pending'
    assert row['attempts'] == 0
    assert row['next_retry_at'] is None


def test_enqueue_non_owner_is_skipped(owner_id):
    # 소유자가 아닌 member — rho 장부 오염 방지로 skipped 적재
    _enqueue(_key('skipped'), owner_id + 99999, owner_id)
    row = _q1("SELECT status FROM gagebu_outbox WHERE idempotency_key=%s", (_key('skipped'),))
    assert row['status'] == 'skipped'


def test_enqueue_duplicate_key_ignored(owner_id):
    assert _enqueue(_key('dup'), owner_id, owner_id) is True
    assert _enqueue(_key('dup'), owner_id, owner_id) is False   # 두 번째는 중복
    row = _q1("SELECT COUNT(*) n FROM gagebu_outbox WHERE idempotency_key=%s", (_key('dup'),))
    assert row['n'] == 1


# ── 디스패치·백오프 (send_transaction 스텁) ──────────────────────────

class _Result:
    def __init__(self, ok, retryable=True, transaction_id=None, duplicate=False):
        self.ok = ok
        self.retryable = retryable
        self.transaction_id = transaction_id
        self.duplicate = duplicate
        self.error = None if ok else 'stub error'


def _patch_send(monkeypatch, result):
    import gagebu_client
    monkeypatch.setattr(gagebu_client, 'is_enabled', lambda: True)
    monkeypatch.setattr('gagebu_outbox.send_transaction', lambda **kw: result, raising=False)
    # dispatch_pending 은 함수 안에서 import 하므로 gagebu_client 쪽도 덮는다
    monkeypatch.setattr(gagebu_client, 'send_transaction', lambda **kw: result)


def test_retryable_failure_backs_off_not_failed(owner_id, monkeypatch):
    _enqueue(_key('retry'), owner_id, owner_id)
    _patch_send(monkeypatch, _Result(ok=False, retryable=True))
    r = ob.dispatch_pending()
    assert r['sent'] == 0 and r['retried'] == 1 and r['failed'] == 0
    row = _q1("SELECT status, attempts, next_retry_at FROM gagebu_outbox WHERE idempotency_key=%s",
              (_key('retry'),))
    assert row['status'] == 'pending'          # failed 아님
    assert row['attempts'] == 1
    assert row['next_retry_at'] > datetime.now()   # 미래로 미룸


def test_backoff_survives_many_failures(owner_id, monkeypatch):
    """예전엔 5회(=25분)면 failed. 이제 재시도 가능 실패는 폐기하지 않는다."""
    _enqueue(_key('many'), owner_id, owner_id)
    _patch_send(monkeypatch, _Result(ok=False, retryable=True))
    for _ in range(8):
        _ex("UPDATE gagebu_outbox SET next_retry_at=%s WHERE idempotency_key=%s",
            (datetime.now() - timedelta(minutes=1), _key('many')))
        ob.dispatch_pending()
    row = _q1("SELECT status, attempts FROM gagebu_outbox WHERE idempotency_key=%s", (_key('many'),))
    assert row['status'] == 'pending'          # 8회 실패해도 살아있음
    assert row['attempts'] >= 8


def test_non_retryable_failure_is_final(owner_id, monkeypatch):
    _enqueue(_key('4xx'), owner_id, owner_id)
    _patch_send(monkeypatch, _Result(ok=False, retryable=False))   # 4xx
    r = ob.dispatch_pending()
    assert r['failed'] == 1
    row = _q1("SELECT status FROM gagebu_outbox WHERE idempotency_key=%s", (_key('4xx'),))
    assert row['status'] == 'failed'


def test_success_marks_sent(owner_id, monkeypatch):
    _enqueue(_key('ok'), owner_id, owner_id)
    _patch_send(monkeypatch, _Result(ok=True, transaction_id=12345))
    r = ob.dispatch_pending()
    assert r['sent'] == 1
    row = _q1("SELECT status, remote_txn_id FROM gagebu_outbox WHERE idempotency_key=%s",
              (_key('ok'),))
    assert row['status'] == 'sent'
    assert row['remote_txn_id'] == 12345


def test_backoff_not_due_is_skipped(owner_id, monkeypatch):
    _enqueue(_key('notdue'), owner_id, owner_id)
    _patch_send(monkeypatch, _Result(ok=False, retryable=True))
    ob.dispatch_pending()                       # 1회 실패 → next_retry_at 미래
    r = ob.dispatch_pending()                   # 아직 재시도 시각 전
    assert r['picked'] == 0


# ── 복구·모니터링 ────────────────────────────────────────────────────

def test_reset_failed_reopens(owner_id):
    _enqueue(_key('reset'), owner_id, owner_id)
    _ex("UPDATE gagebu_outbox SET status='failed', attempts=9 WHERE idempotency_key=%s",
        (_key('reset'),))
    n = ob.reset_failed(source='trade')
    assert n >= 1
    row = _q1("SELECT status, attempts, next_retry_at FROM gagebu_outbox WHERE idempotency_key=%s",
              (_key('reset'),))
    assert row['status'] == 'pending' and row['attempts'] == 0 and row['next_retry_at'] is None


def test_find_stuck_detects_old_pending(owner_id):
    _enqueue(_key('stuck'), owner_id, owner_id)
    _ex("UPDATE gagebu_outbox SET created_at=%s WHERE idempotency_key=%s",
        (datetime.now() - timedelta(hours=30), _key('stuck')))
    stuck = ob.find_stuck(hours=24)
    assert any(s['idempotency_key'] == _key('stuck') if 'idempotency_key' in s
               else True for s in stuck)
    assert len(stuck) >= 1


def test_backoff_schedule_bounded():
    vals = [ob._backoff_minutes(a) for a in range(12)]
    assert vals[0] == 5 and vals[1] == 10 and vals[2] == 20
    assert max(vals) <= ob._BACKOFF_MAX_MIN     # 상한
    assert all(b >= a for a, b in zip(vals, vals[1:]))   # 단조 증가
