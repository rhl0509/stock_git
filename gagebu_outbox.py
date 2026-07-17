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
from datetime import datetime

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5      # 이후 failed 로 고정. 무한 재시도로 로그를 태우지 않는다.
_BATCH = 50


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


def dispatch_pending(limit: int = _BATCH) -> dict:
    """
    pending 행을 가계부로 전송한다. 디스패처 잡이 주기적으로 호출.

    전송 실패는 행에 남고(attempts/last_error) 다음 주기에 다시 집는다.
    재시도 불가(4xx)면 즉시 failed 로 고정한다 — 같은 요청은 결과가 같다.
    """
    from database.db_connection import get_db_connection
    from gagebu_client import is_enabled, send_transaction

    if not is_enabled():
        return {'skipped': True, 'reason': 'GAGEBU_INGEST_TOKEN 미설정'}

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id, idempotency_key, source, payload, attempts
                   FROM gagebu_outbox
                   WHERE status = 'pending' AND attempts < %s
                   ORDER BY id LIMIT %s""",
                (_MAX_ATTEMPTS, limit),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    sent = dup = failed = 0
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
                    # attempts 는 DB 에서 증가시킨다(읽은 값을 덮으면 동시 실행 시 lost update).
                    final = (not retryable) or (row['attempts'] + 1) >= _MAX_ATTEMPTS
                    cursor.execute(
                        """UPDATE gagebu_outbox
                           SET status=%s, attempts=attempts+1, last_error=%s
                           WHERE id=%s""",
                        ('failed' if final else 'pending', (err or '')[:1000], row['id']),
                    )
                    if final:
                        failed += 1
            conn.commit()
        finally:
            conn.close()

    if rows:
        logger.info(f'[gagebu_outbox] 전송 {sent}건(중복 {dup}) 실패확정 {failed}건 '
                    f'/ 대상 {len(rows)}건')
    return {'picked': len(rows), 'sent': sent, 'duplicate': dup, 'failed': failed}
