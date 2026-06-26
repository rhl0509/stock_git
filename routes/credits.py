"""routes/credits.py — 크레딧 충전/차감 (포트원 PortOne V2 결제).

설계
----
· 결제는 포트원(PortOne) V2 결제창 + REST 검증으로 처리한다.
· 충전 1원 = 1크레딧 (정수). 차감은 deduct_credits() 로 서버 내부에서만 호출.
· 카드정보 등 민감정보는 저장하지 않는다. 거래/잔액 레코드만 DB에 남긴다.

테스트(mock) 모드
-----------------
PORTONE_API_SECRET 가 비어 있으면 mock 모드로 동작한다.
  · prepare  → mock 결제 식별자 발급
  · verify   → 실제 PG 호출 없이 결제 성공으로 간주하고 즉시 충전
이렇게 하면 키 없이도 충전 흐름 전체를 UI에서 테스트할 수 있다.

테이블
------
user_credits          : 회원별 현재 잔액
credit_transactions   : 충전/차감 원장(ledger)
payments              : 결제 시도 기록(포트원 paymentId, 금액, 상태)
"""
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime

import requests
from fastapi import APIRouter, Request, Body, Depends
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from config import Config
from routes.utils import require_owner

router = APIRouter()
logger = logging.getLogger(__name__)

# 허용 충전 금액(원). 임의 금액 결제를 막아 검증을 단순화한다.
ALLOWED_AMOUNTS = (5000, 10000, 30000, 50000, 100000, 1000)  # 1000원: 결제 테스트용

PORTONE_API_BASE = "https://api.portone.io"


def _is_mock() -> bool:
    """포트원 시크릿이 없으면 mock 모드."""
    return not bool(Config.PORTONE_API_SECRET)


def _ensure_table():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_credits (
                    user_no    INT          NOT NULL PRIMARY KEY,
                    balance    BIGINT       NOT NULL DEFAULT 0,
                    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS credit_transactions (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    user_no       INT          NOT NULL,
                    kind          VARCHAR(10)  NOT NULL,        -- charge / deduct
                    amount        BIGINT       NOT NULL,        -- 부호 없는 절대값
                    balance_after BIGINT       NOT NULL,
                    ref           VARCHAR(80),                  -- 결제 paymentId 등
                    memo          VARCHAR(200),
                    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user (user_no),
                    INDEX idx_created (created_at)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    user_no     INT          NOT NULL,
                    payment_id  VARCHAR(80)  NOT NULL UNIQUE,   -- 포트원 paymentId(merchant uid)
                    amount      BIGINT       NOT NULL,
                    credits     BIGINT       NOT NULL,
                    status      VARCHAR(12)  NOT NULL DEFAULT 'pending',  -- pending/paid/failed/cancelled
                    method      VARCHAR(40),
                    pg_tx_id    VARCHAR(120),
                    is_mock     TINYINT(1)   DEFAULT 0,
                    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    paid_at     DATETIME,
                    cancel_reason VARCHAR(200),
                    cancelled_at  DATETIME,
                    INDEX idx_user (user_no),
                    INDEX idx_status (status)
                )
            """)
            # 기존 테이블에도 환불 컬럼 보강(없을 때만 추가)
            _ensure_column(cur, 'payments', 'cancel_reason', "VARCHAR(200) NULL")
            _ensure_column(cur, 'payments', 'cancelled_at',  "DATETIME NULL")
        conn.commit()
    finally:
        conn.close()


def _ensure_column(cur, table: str, col: str, ddl: str):
    """information_schema 로 컬럼 존재를 확인하고 없으면 ADD COLUMN(멱등 마이그레이션)."""
    cur.execute(
        "SELECT COUNT(*) AS c FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
        (table, col))
    row = cur.fetchone()
    if not (row and int(row['c']) > 0):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _get_balance(cur, user_no: int) -> int:
    cur.execute("SELECT balance FROM user_credits WHERE user_no=%s", (user_no,))
    row = cur.fetchone()
    return int(row['balance']) if row else 0


def _apply_delta(cur, user_no: int, kind: str, amount: int, ref: str | None, memo: str | None) -> int:
    """잔액에 delta(charge=+, deduct=-) 적용 후 원장 기록. 새 잔액 반환.
    호출자가 트랜잭션/락을 관리한다(SELECT ... FOR UPDATE 권장)."""
    bal = _get_balance(cur, user_no)
    new_bal = bal + amount if kind == 'charge' else bal - amount
    cur.execute(
        "INSERT INTO user_credits (user_no, balance) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE balance=%s",
        (user_no, new_bal, new_bal))
    cur.execute(
        "INSERT INTO credit_transactions (user_no, kind, amount, balance_after, ref, memo) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (user_no, kind, abs(amount), new_bal, ref, memo))
    return new_bal


def _apply_payment_paid(cur, pay, method, pg_tx_id) -> int:
    """payments 행을 paid 로 마킹하고 크레딧을 충전한다. 새 잔액 반환.
    호출자가 트랜잭션/락(SELECT ... FOR UPDATE)을 관리한다. verify·webhook 공용."""
    cur.execute(
        "UPDATE payments SET status='paid', method=%s, pg_tx_id=%s, paid_at=NOW() "
        "WHERE payment_id=%s",
        (str(method)[:40] if method else None,
         str(pg_tx_id)[:120] if pg_tx_id else None,
         pay['payment_id']))
    return _apply_delta(cur, pay['user_no'], 'charge', int(pay['credits']),
                        pay['payment_id'], f"크레딧 {int(pay['amount']):,}원 충전")


def _apply_payment_cancelled(cur, pay, reason: str) -> tuple[int, int]:
    """payments 를 cancelled 로 마킹하고 크레딧을 회수(원장 deduct)한다.
    이미 사용된 분은 회수할 수 없으므로 회수액을 현재 잔액으로 clamp(잔액 음수 방지).
    반환 (실제 회수액, 새 잔액). 호출자가 트랜잭션/락을 관리한다."""
    credits = int(pay['credits'])
    bal     = _get_balance(cur, pay['user_no'])
    reclaim = min(credits, max(bal, 0))
    new_bal = bal
    if reclaim > 0:
        new_bal = _apply_delta(cur, pay['user_no'], 'deduct', reclaim,
                               pay['payment_id'], f"환불 회수: {reason}"[:200])
    if reclaim < credits:
        logger.warning(f"[credits/cancel] {pay['payment_id']} 일부만 회수(사용분 존재): "
                       f"회수 {reclaim}/{credits}")
    cur.execute(
        "UPDATE payments SET status='cancelled', cancel_reason=%s, cancelled_at=NOW() "
        "WHERE payment_id=%s",
        (str(reason)[:200], pay['payment_id']))
    return reclaim, new_bal


def _extract_payment_result(info: dict) -> tuple:
    """포트원 V2 단건 조회 응답에서 (status, paid_amount, method, pg_tx_id) 추출."""
    status      = info.get('status')
    paid_amount = int(((info.get('amount') or {}).get('total')) or 0)
    method      = (info.get('method') or {}).get('type') or (info.get('channel') or {}).get('pgProvider')
    pg_tx_id    = info.get('pgTxId') or info.get('id')
    return status, paid_amount, method, pg_tx_id


def get_balance_value(user_no: int) -> int:
    """회원의 현재 크레딧 잔액을 반환(자체 커넥션). 차감 전 잔액 확인용."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            return _get_balance(cur, user_no)
    finally:
        conn.close()


def deduct_credits(user_no: int, amount: int, memo: str = '') -> dict:
    """서버 내부에서 크레딧을 차감한다(예: 향후 Claude API 사용 시).
    반환: {ok: bool, balance: int, error?: str}. 잔액 부족 시 차감하지 않는다."""
    if amount <= 0:
        return {"ok": True, "balance": None}
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM user_credits WHERE user_no=%s FOR UPDATE", (user_no,))
            row = cur.fetchone()
            bal = int(row['balance']) if row else 0
            if bal < amount:
                conn.rollback()
                return {"ok": False, "balance": bal, "error": "크레딧이 부족합니다."}
            new_bal = _apply_delta(cur, user_no, 'deduct', amount, None, memo)
        conn.commit()
        return {"ok": True, "balance": new_bal}
    except Exception as e:
        conn.rollback()
        logger.error(f"[credits/deduct] {e}", exc_info=True)
        return {"ok": False, "balance": None, "error": "차감 중 오류"}
    finally:
        conn.close()


@router.get('/api/credits/balance')
def get_balance(request: Request):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            bal = _get_balance(cur, request.session['user_no'])
        from routes.utils import is_owner
        from routes.tier import effective_role
        return JSONResponse({
            "balance":      bal,
            "mock":         _is_mock(),
            "chat_enabled": bool(Config.ANTHROPIC_API_KEY),
            "chat_cost":    Config.CHAT_CREDIT_COST,
            "role":         effective_role(request),
            "is_owner":     is_owner(request),
        })
    finally:
        conn.close()


@router.post('/api/credits/charge/prepare')
def charge_prepare(request: Request, data: dict = Body(default={})):
    """충전 결제 준비. payments 에 pending 행을 만들고 결제창에 필요한 값을 돌려준다."""
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    user_no = request.session['user_no']
    try:
        amount = int(data.get('amount') or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "금액이 올바르지 않습니다."}, status_code=400)
    if amount not in ALLOWED_AMOUNTS:
        return JSONResponse({"error": "허용되지 않은 충전 금액입니다."}, status_code=400)

    payment_id = f"credit_{user_no}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"
    mock = _is_mock()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO payments (user_no, payment_id, amount, credits, status, is_mock) "
                "VALUES (%s,%s,%s,%s,'pending',%s)",
                (user_no, payment_id, amount, amount, 1 if mock else 0))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"[credits/prepare] {e}", exc_info=True)
        return JSONResponse({"error": "결제 준비 중 오류"}, status_code=500)
    finally:
        conn.close()

    return JSONResponse({
        "payment_id":  payment_id,
        "amount":      amount,
        "order_name":  f"크레딧 {amount:,}원 충전",
        "store_id":    Config.PORTONE_STORE_ID,
        "channel_key": Config.PORTONE_CHANNEL_KEY,
        "mock":        mock,
    })


def _portone_fetch(payment_id: str) -> dict | None:
    """포트원 V2 단건 결제 조회. 실패 시 None."""
    try:
        resp = requests.get(
            f"{PORTONE_API_BASE}/payments/{payment_id}",
            headers={"Authorization": f"PortOne {Config.PORTONE_API_SECRET}"},
            timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[credits/verify] portone {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as e:
        logger.error(f"[credits/verify] portone 호출 오류: {e}")
        return None


def _portone_cancel(payment_id: str, reason: str) -> dict | None:
    """포트원 V2 결제 전액 취소(환불). 성공 시 응답 dict, 실패 시 None."""
    try:
        resp = requests.post(
            f"{PORTONE_API_BASE}/payments/{payment_id}/cancel",
            headers={"Authorization": f"PortOne {Config.PORTONE_API_SECRET}",
                     "Content-Type": "application/json"},
            json={"reason": reason},
            timeout=10)
        if resp.status_code not in (200, 201):
            logger.warning(f"[credits/refund] portone cancel {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as e:
        logger.error(f"[credits/refund] portone cancel 호출 오류: {e}")
        return None


def _verify_webhook_signature(body: bytes, headers) -> bool:
    """포트원 V2 웹훅 서명 검증(Standard Webhooks 규격).
    시크릿(whsec_...) 미설정이거나 헤더 누락/타임스탬프 초과/서명 불일치면 False.
    위·변조된 결제완료 통지로 크레딧이 부정 충전되는 것을 막는다."""
    secret = Config.PORTONE_WEBHOOK_SECRET
    if not secret:
        return False
    wid  = headers.get('webhook-id')
    wts  = headers.get('webhook-timestamp')
    wsig = headers.get('webhook-signature')
    if not (wid and wts and wsig):
        return False
    try:                                   # 재전송 공격 완화(±5분)
        if abs(time.time() - int(wts)) > 300:
            return False
    except (TypeError, ValueError):
        return False
    key = secret.split('_', 1)[1] if secret.startswith('whsec_') else secret
    try:
        key_bytes = base64.b64decode(key)
    except Exception:
        key_bytes = secret.encode()
    signed   = f"{wid}.{wts}.".encode() + body
    expected = base64.b64encode(hmac.new(key_bytes, signed, hashlib.sha256).digest()).decode()
    # 헤더는 "v1,<sig> v1,<sig2>" 형태(공백 구분, 다중 서명 가능)
    for part in wsig.split():
        sig = part.split(',', 1)[1] if ',' in part else part
        if hmac.compare_digest(sig, expected):
            return True
    return False


def _handle_webhook_paid(payment_id: str):
    """웹훅 결제완료 처리. pending 행만 멱등 충전. 일시 오류는 raise 하여 PG 재전송 유도."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM payments WHERE payment_id=%s AND status='pending' FOR UPDATE",
                (payment_id,))
            pay = cur.fetchone()
            if not pay:                    # 없음 또는 이미 paid/cancelled → 멱등 종료
                conn.rollback()
                return
            if _is_mock():
                method, pg_tx_id = 'mock', f"mock_{uuid.uuid4().hex[:12]}"
            else:
                info = _portone_fetch(payment_id)
                if not info:
                    conn.rollback()
                    raise RuntimeError("portone 조회 실패")   # → 500 → 재전송
                status, paid_amount, method, pg_tx_id = _extract_payment_result(info)
                if not (status == 'PAID' and paid_amount == int(pay['amount'])):
                    conn.rollback()
                    logger.warning(f"[credits/webhook] 금액/상태 불일치 status={status} amt={paid_amount}")
                    return
            _apply_payment_paid(cur, pay, method, pg_tx_id)
        conn.commit()
        from routes.tier import promote_on_charge
        promote_on_charge(pay['user_no'])
        logger.info(f"[credits/webhook] 충전 확정: {payment_id} (user {pay['user_no']}, {pay['credits']})")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _handle_webhook_cancelled(payment_id: str):
    """웹훅 결제취소 처리. PG 콘솔 등 외부 취소도 반영. 이미 cancelled 면 멱등 종료."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE payment_id=%s FOR UPDATE", (payment_id,))
            pay = cur.fetchone()
            if not pay or pay['status'] == 'cancelled':
                conn.rollback()
                return
            _apply_payment_cancelled(cur, pay, 'PG 취소(webhook)')
        conn.commit()
        logger.info(f"[credits/webhook] 결제취소 반영: {payment_id}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post('/api/credits/charge/verify')
def charge_verify(request: Request, data: dict = Body(default={})):
    """결제 검증 후 크레딧 충전. mock 모드에선 PG 호출 없이 성공 처리."""
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    user_no = request.session['user_no']
    payment_id = (data.get('payment_id') or '').strip()
    if not payment_id:
        return JSONResponse({"error": "payment_id가 필요합니다."}, status_code=400)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM payments WHERE payment_id=%s AND user_no=%s FOR UPDATE",
                (payment_id, user_no))
            pay = cur.fetchone()
            if not pay:
                conn.rollback()
                return JSONResponse({"error": "결제 내역을 찾을 수 없습니다."}, status_code=404)
            if pay['status'] == 'paid':
                # 이미 처리됨(중복 검증) — 멱등 응답
                bal = _get_balance(cur, user_no)
                conn.rollback()
                return JSONResponse({"status": "paid", "balance": bal, "already": True})

            expected = int(pay['amount'])
            method = None
            pg_tx_id = None

            if _is_mock():
                paid_ok = True
                method = 'mock'
                pg_tx_id = f"mock_{uuid.uuid4().hex[:12]}"
            else:
                info = _portone_fetch(payment_id)
                if not info:
                    conn.rollback()
                    return JSONResponse({"error": "결제 정보를 확인할 수 없습니다."}, status_code=502)
                status, paid_amount, method, pg_tx_id = _extract_payment_result(info)
                paid_ok = (status == 'PAID' and paid_amount == expected)
                if not paid_ok:
                    cur.execute(
                        "UPDATE payments SET status='failed', method=%s, pg_tx_id=%s WHERE payment_id=%s",
                        (str(method)[:40] if method else None, str(pg_tx_id)[:120] if pg_tx_id else None, payment_id))
                    conn.commit()
                    return JSONResponse(
                        {"error": f"결제가 완료되지 않았습니다(status={status}, amount={paid_amount}).",
                         "status": "failed"}, status_code=400)

            new_bal = _apply_payment_paid(cur, pay, method, pg_tx_id)
        conn.commit()
        # 충전 성공 → free 면 basic 으로 자동 승급(세션도 즉시 갱신).
        from routes.tier import promote_on_charge
        promoted = promote_on_charge(user_no)
        if promoted:
            request.session['role'] = promoted
        return JSONResponse({"status": "paid", "balance": new_bal,
                             "charged": int(pay['credits']), "promoted_to": promoted})
    except Exception as e:
        conn.rollback()
        logger.error(f"[credits/verify] {e}", exc_info=True)
        return JSONResponse({"error": "결제 검증 중 오류"}, status_code=500)
    finally:
        conn.close()


@router.get('/api/credits/transactions')
def list_transactions(request: Request, limit: int = 50):
    if 'user_no' not in request.session:
        return JSONResponse({"error": "로그인 필요"}, status_code=401)
    limit = max(1, min(int(limit or 50), 200))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, amount, balance_after, ref, memo, "
                "DATE_FORMAT(created_at,'%%Y-%%m-%%d %%H:%%i:%%s') AS created_at "
                "FROM credit_transactions WHERE user_no=%s "
                "ORDER BY id DESC LIMIT %s",
                (request.session['user_no'], limit))
            rows = cur.fetchall()
        return JSONResponse({"transactions": rows})
    finally:
        conn.close()


@router.post('/api/credits/webhook')
async def credits_webhook(request: Request):
    """포트원 V2 웹훅 수신. 결제완료 통지를 서버가 직접 받아 충전을 확정한다.
    사용자가 결제창을 닫아 verify 가 호출되지 못해도 충전 누락을 막는 안전망.
    서명 검증 실패→400, 처리 중 일시 오류→500(PG 재전송), 정상/무시→200."""
    raw = await request.body()
    if not _verify_webhook_signature(raw, request.headers):
        logger.warning("[credits/webhook] 서명 검증 실패 — 거부")
        return JSONResponse({"error": "invalid signature"}, status_code=400)
    try:
        evt = json.loads(raw.decode('utf-8'))
    except Exception:
        return JSONResponse({"error": "invalid body"}, status_code=400)

    etype      = evt.get('type') or ''
    payment_id = ((evt.get('data') or {}).get('paymentId') or '').strip()
    if not payment_id:
        return JSONResponse({"ok": True})          # 결제 외 이벤트는 무시

    try:
        if etype == 'Transaction.Paid':
            _handle_webhook_paid(payment_id)
        elif etype in ('Transaction.Cancelled', 'Transaction.PartialCancelled'):
            _handle_webhook_cancelled(payment_id)
        # 그 외 타입(준비/가상계좌 발급 등)은 무시
    except Exception as e:
        logger.error(f"[credits/webhook] 처리 오류({etype}): {e}", exc_info=True)
        return JSONResponse({"error": "processing error"}, status_code=500)
    return JSONResponse({"ok": True})


@router.post('/api/credits/refund', dependencies=[Depends(require_owner)])
def charge_refund(request: Request, data: dict = Body(default={})):
    """[운영자 전용] 충전 결제를 취소(환불)하고 크레딧을 회수한다.
    정책: 회수 대상 회원의 잔액이 충전분보다 적으면(이미 사용) 환불을 거부(409)한다
          — 충전→사용→환불로 크레딧을 탈취하는 것을 차단."""
    payment_id = (data.get('payment_id') or '').strip()
    reason     = (data.get('reason') or '운영자 환불').strip()
    if not payment_id:
        return JSONResponse({"error": "payment_id가 필요합니다."}, status_code=400)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE payment_id=%s FOR UPDATE", (payment_id,))
            pay = cur.fetchone()
            if not pay:
                conn.rollback()
                return JSONResponse({"error": "결제 내역을 찾을 수 없습니다."}, status_code=404)
            if pay['status'] == 'cancelled':
                conn.rollback()
                return JSONResponse({"status": "cancelled", "already": True})
            if pay['status'] != 'paid':
                conn.rollback()
                return JSONResponse({"error": f"환불 불가 상태입니다(status={pay['status']})."},
                                    status_code=400)

            credits = int(pay['credits'])
            bal     = _get_balance(cur, pay['user_no'])
            if bal < credits:
                conn.rollback()
                return JSONResponse(
                    {"error": f"이미 사용된 크레딧이 있어 환불할 수 없습니다(잔액 {bal} < 충전 {credits})."},
                    status_code=409)

            if not _is_mock():                      # 실결제면 PG 취소 먼저
                if not _portone_cancel(payment_id, reason):
                    conn.rollback()
                    return JSONResponse({"error": "PG 결제 취소에 실패했습니다."}, status_code=502)

            reclaim, new_bal = _apply_payment_cancelled(cur, pay, reason)
        conn.commit()
        logger.info(f"[credits/refund] 환불 완료: {payment_id} (user {pay['user_no']}, 회수 {reclaim})")
        return JSONResponse({"status": "cancelled", "reclaimed": reclaim,
                             "user_no": pay['user_no'], "balance_after": new_bal,
                             "mock": _is_mock()})
    except Exception as e:
        conn.rollback()
        logger.error(f"[credits/refund] {e}", exc_info=True)
        return JSONResponse({"error": "환불 처리 중 오류"}, status_code=500)
    finally:
        conn.close()
