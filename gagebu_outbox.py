"""가계부 자동기록 아웃박스 — 적재(enqueue)와 전송(dispatch).

■ 왜 아웃박스인가
  매수/매도는 자기 DB(stock_stack)에 원자적으로 커밋돼야 하는데, 가계부 기록은
  이제 별도 앱의 HTTP 호출이다. 그 호출을 매매 트랜잭션 안에서 하면:
    ① 가계부가 죽으면 매수가 실패한다(본 기능이 부수효과에 인질이 된다)
    ② HTTP 는 롤백되지 않는다 — 보낸 뒤 커밋이 실패하면 유령 거래가 남는다
    ③ 요청 응답이 상대 서비스 지연에 묶인다
  그래서 매매와 **같은 커밋**으로 의도만 적재하고, 전송은 디스패처가 분리해 재시도한다.

■ 소유자 게이트
  GAGEBU_INGEST_TOKEN 은 rho 의 장부에 매핑된 단일 자격증명이다. 다른 회원의 매매를
  그 토큰으로 보내면 rho 장부에 남의 거래가 들어간다. 소유자가 아니면 'skipped' 로
  적재한다 — 행을 안 만들면 "왜 연동이 안 됐는지" 를 알 수 없어진다.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_BATCH = 50

# 지수 백오프 상한(분). 재시도 가능 실패(연결 거부·5xx)는 attempts 로 폐기하지 않고
# next_retry_at 을 뒤로 미룬다: 5분→10→20→40→80→…→최대 720분(12h). 가계부가 밤새
# 꺼져 있어도 살아나면 따라잡는다.
_BACKOFF_BASE_MIN = 5
_BACKOFF_MAX_MIN = 720
# 이 시간(시간)을 넘도록 pending 인 행은 "오래 막힘"으로 한 번 알린다(폐기하지 않음).
_STUCK_ALERT_HOURS = 24


def make_key(*parts: str) -> str:
    """멱등키 = SHA2-256('a|b|c'). 가계부의 stock_ingest_ledger 와 같은 규약."""
    return hashlib.sha256('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()


def enqueue(cursor, *, idempotency_key: str, source: str, member_id: int,
            type_val: str, amount: int, title: str, date_str: str,
            category_hint: str = '', owner_user_no: int | None) -> bool:
    """
    아웃박스에 1건 적재. **호출자의 커서·트랜잭션을 그대로 쓴다** — 매매와 같은 커밋에
    들어가야 원자성이 유지되므로 여기서 commit 하지 않는다.

    소유자가 아니면 status='skipped' (전송 대상 아님, 기록은 남긴다).

    Returns:
        True = 새로 적재, False = 이미 있던 키(중복).

    ⚠️ INSERT IGNORE 를 쓰지 않는다. IGNORE 는 중복키뿐 아니라 truncation·NOT NULL
    위반 등 **모든 에러를 경고로 강등**해, 멱등키가 잘못 만들어졌을 때 매매가 통째로
    조용히 사라진다. ON DUPLICATE KEY UPDATE 로 중복만 흡수하고 나머지는 예외로 올린다
    (호출자의 트랜잭션이 롤백되어 매매도 함께 실패 → 무증상 유실 대신 시끄러운 실패).
    """
    status = 'pending' if (owner_user_no is not None and member_id == owner_user_no) \
        else 'skipped'
    payload = {'type': type_val, 'amount': int(amount), 'title': title,
               'date': date_str}
    if category_hint:
        payload['category_hint'] = category_hint

    cursor.execute(
        """INSERT INTO gagebu_outbox
               (idempotency_key, source, member_id, payload, status)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE id = id""",
        (idempotency_key, source, member_id,
         json.dumps(payload, ensure_ascii=False), status),
    )
    # ON DUPLICATE KEY UPDATE: 신규 삽입=1, 기존 행 무변경=0.
    created = cursor.rowcount == 1
    if not created:
        logger.warning(f'[gagebu_outbox] 중복 적재 무시 {source} {idempotency_key[:12]} '
                       f'member={member_id} — 멱등키가 의도대로인지 확인할 것')
    return created


def _backoff_minutes(attempts: int) -> int:
    """attempts 회 실패 후 다음 재시도까지 대기(분). 지수, 상한 있음."""
    return min(_BACKOFF_BASE_MIN * (2 ** max(0, attempts)), _BACKOFF_MAX_MIN)


def dispatch_pending(limit: int = _BATCH) -> dict:
    """
    재시도 시각이 된 pending 행을 가계부로 전송한다. 디스패처 잡이 주기적으로 호출.

    재시도 가능 실패(연결 거부·5xx·429)는 attempts 로 폐기하지 않고 next_retry_at 을
    지수 백오프로 미룬다 — 가계부가 오래 죽어 있어도 살아나면 따라잡는다.
    재시도 불가(4xx)·payload 파손은 즉시 failed 로 고정한다(같은 요청은 결과가 같다).
    """
    from database.db_connection import get_db_connection
    from gagebu_client import is_enabled, send_transaction

    if not is_enabled():
        return {'skipped': True, 'reason': 'GAGEBU_INGEST_TOKEN 미설정'}

    now = datetime.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # next_retry_at 이 NULL(첫 시도)이거나 도래한 행만 집는다.
            cursor.execute(
                """SELECT id, idempotency_key, source, payload, attempts
                   FROM gagebu_outbox
                   WHERE status = 'pending'
                     AND (next_retry_at IS NULL OR next_retry_at <= %s)
                   ORDER BY id LIMIT %s""",
                (now, limit),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    sent = dup = failed = retried = 0
    for row in rows:
        # 행별 예외 격리 — 한 행이 던지면 루프가 죽고, 그 행은 attempts 가 안 오른 채
        # pending 으로 남아 ORDER BY id 가 다음 주기에도 그 행을 선두로 집는다.
        # poison row 하나가 큐 전체를 영구 정지시키는 무증상 실패가 된다.
        try:
            p = row['payload']
            if isinstance(p, str):      # 드라이버/서버에 따라 str 로 올 수 있다
                p = json.loads(p)
            result = send_transaction(
                idempotency_key=row['idempotency_key'], source=row['source'],
                type_val=p['type'], amount=p['amount'], title=p['title'],
                date_str=p['date'], category_hint=p.get('category_hint', ''),
            )
        except Exception as e:
            logger.error(f'[gagebu_outbox] 행 {row["id"]} 처리 실패: {e}', exc_info=True)
            result = None

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if result is not None and result.ok:
                    cursor.execute(
                        """UPDATE gagebu_outbox
                           SET status='sent', remote_txn_id=%s, sent_at=%s,
                               attempts=attempts+1, last_error=NULL
                           WHERE id=%s""",
                        (result.transaction_id, datetime.now(), row['id']),
                    )
                    sent += 1
                    if result.duplicate:
                        dup += 1
                else:
                    # payload 가 깨진 경우(result is None)는 재시도해도 같으므로 즉시 확정.
                    retryable = result.retryable if result is not None else False
                    err = (result.error if result is not None
                           else 'payload 처리 실패 — 로그 확인')
                    if not retryable:
                        # 4xx·payload 파손 → 즉시 failed. 백오프해도 결과가 같다.
                        cursor.execute(
                            """UPDATE gagebu_outbox
                               SET status='failed', attempts=attempts+1, last_error=%s
                               WHERE id=%s""",
                            ((err or '')[:1000], row['id']),
                        )
                        failed += 1
                    else:
                        # 재시도 가능 → pending 유지, next_retry_at 을 백오프로 미룬다.
                        # attempts 로 폐기하지 않는다(가계부 장기 다운을 견디게).
                        wait = _backoff_minutes(row['attempts'] + 1)
                        cursor.execute(
                            """UPDATE gagebu_outbox
                               SET attempts=attempts+1,
                                   next_retry_at=%s, last_error=%s
                               WHERE id=%s""",
                            (now + timedelta(minutes=wait), (err or '')[:1000], row['id']),
                        )
                        retried += 1
            conn.commit()
        finally:
            conn.close()

    if rows:
        logger.info(f'[gagebu_outbox] 전송 {sent}건(중복 {dup}) 재시도대기 {retried}건 '
                    f'실패확정 {failed}건 / 대상 {len(rows)}건')
    return {'picked': len(rows), 'sent': sent, 'duplicate': dup,
            'retried': retried, 'failed': failed}


def find_stuck(hours: int = _STUCK_ALERT_HOURS) -> list[dict]:
    """생성 후 hours 시간이 지나도록 못 보낸 pending 행. 알림·모니터링용."""
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id, source, member_id, attempts, last_error, created_at
                   FROM gagebu_outbox
                   WHERE status='pending' AND created_at < %s
                   ORDER BY id""",
                (datetime.now() - timedelta(hours=hours),),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def reset_failed(source: str | None = None) -> int:
    """failed 행을 pending 으로 되돌린다(재시도 재개). 반환: 되돌린 행 수.

    4xx 로 실패한 행(입력·인증 문제)은 근본 원인을 고친 뒤 이걸 호출해야 의미가 있다
    — 그대로 되돌리면 같은 4xx 로 다시 failed 된다. attempts·next_retry_at 을 리셋해
    즉시 재시도 대상으로 만든다. 멱등이라 이미 기록된 건은 가계부가 duplicate 로 흡수한다.

    운영에서 호출: python -c "import gagebu_outbox as o; print(o.reset_failed())"
    """
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if source:
                cursor.execute(
                    """UPDATE gagebu_outbox
                       SET status='pending', attempts=0, next_retry_at=NULL,
                           last_error=NULL
                       WHERE status='failed' AND source=%s""",
                    (source,),
                )
            else:
                cursor.execute(
                    """UPDATE gagebu_outbox
                       SET status='pending', attempts=0, next_retry_at=NULL,
                           last_error=NULL
                       WHERE status='failed'""",
                )
            n = cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    logger.info(f'[gagebu_outbox] failed → pending 복구 {n}건'
                + (f' (source={source})' if source else ''))
    return n
