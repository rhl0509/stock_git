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
import logging
import uuid
from datetime import datetime

import requests
from fastapi import APIRouter, Request, Body
from fastapi.responses import JSONResponse

from database.db_connection import get_db_connection
from config import Config

router = APIRouter()
logger = logging.getLogger(__name__)

# 허용 충전 금액(원). 임의 금액 결제를 막아 검증을 단순화한다.
ALLOWED_AMOUNTS = (5000, 10000, 30000, 50000, 100000)

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
                    status      VARCHAR(12)  NOT NULL DEFAULT 'pending',  -- pending/paid/failed
                    method      VARCHAR(40),
                    pg_tx_id    VARCHAR(120),
                    is_mock     TINYINT(1)   DEFAULT 0,
                    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    paid_at     DATETIME,
                    INDEX idx_user (user_no),
                    INDEX idx_status (status)
                )
            """)
        conn.commit()
    finally:
        conn.close()


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
        return JSONResponse({
            "balance":      bal,
            "mock":         _is_mock(),
            "chat_enabled": bool(Config.ANTHROPIC_API_KEY),
            "chat_cost":    Config.CHAT_CREDIT_COST,
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
                status = info.get('status')
                paid_amount = ((info.get('amount') or {}).get('total'))
                paid_ok = (status == 'PAID' and int(paid_amount or 0) == expected)
                method = (info.get('method') or {}).get('type') or info.get('channel', {}).get('pgProvider')
                pg_tx_id = info.get('pgTxId') or info.get('id')
                if not paid_ok:
                    cur.execute(
                        "UPDATE payments SET status='failed', method=%s, pg_tx_id=%s WHERE payment_id=%s",
                        (str(method)[:40] if method else None, str(pg_tx_id)[:120] if pg_tx_id else None, payment_id))
                    conn.commit()
                    return JSONResponse(
                        {"error": f"결제가 완료되지 않았습니다(status={status}, amount={paid_amount}).",
                         "status": "failed"}, status_code=400)

            cur.execute(
                "UPDATE payments SET status='paid', method=%s, pg_tx_id=%s, paid_at=NOW() "
                "WHERE payment_id=%s",
                (str(method)[:40] if method else None, str(pg_tx_id)[:120] if pg_tx_id else None, payment_id))
            new_bal = _apply_delta(cur, user_no, 'charge', int(pay['credits']),
                                   payment_id, f"크레딧 {expected:,}원 충전")
        conn.commit()
        return JSONResponse({"status": "paid", "balance": new_bal, "charged": int(pay['credits'])})
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
