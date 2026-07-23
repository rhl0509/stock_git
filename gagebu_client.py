"""가계부(d:\\expense_tracker, 기본 8010) 자동기록 클라이언트.

■ 신뢰 모델: 토큰을 **가계부가 발급한다**
  이 앱이 JWT 를 서명해 보내는 안을 검토했으나 기각했다 — 그러면 이 앱이 가계부
  데이터의 신원 공급자가 되고, 이 앱은 공개 회원가입(routes/auth.py:68)이라 그
  가입 정책이 곧 가계부의 가입 정책이 된다. 가계부는 rho 1인의 사적 장부다.
  가계부가 발급하면 이 앱은 "누구의 어느 장부에 쓸지" 를 주장할 수단 자체가 없다
  — 토큰 행이 member_id·account_book_id 를 결정한다.

■ 토큰은 하나다 → 소유자만 보낸다
  GAGEBU_INGEST_TOKEN 은 rho 의 장부에 매핑된 단일 자격증명이다. 다른 회원의 매매를
  이 토큰으로 보내면 rho 장부에 남의 거래가 들어간다. 호출자(아웃박스 적재 지점)가
  OWNER_USER_NO 게이트를 책임진다.

■ 이 레포 관례를 따른다
  동기 requests(httpx 미설치), 짧은 타임아웃, 재시도는 여기서 안 한다(디스패처가
  아웃박스 행을 다시 집는다), 실패는 로그 + 결과 객체 반환(예외를 밖으로 안 던진다).

■ 설정
  GAGEBU_BASE_URL   기본 http://127.0.0.1:8010
      ⚠ 127.0.0.1 고정이 기본인 이유: 가계부는 Tailscale 로도 도달 가능하고
        (expense_tracker/frontend/next.config.ts 의 allowedDevOrigins) 세션 쿠키가
        https_only=False 다. 평문 토큰을 로컬 루프백 밖으로 내보내지 않는다.
  GAGEBU_INGEST_TOKEN  가계부에서 발급(POST /integration/tokens). 없으면 연동 비활성.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = os.getenv('GAGEBU_BASE_URL', 'http://127.0.0.1:8010').rstrip('/')
_TIMEOUT = 10          # kis_client 5~7초, notify/telegram 10초 — 그 관례 범위
_INGEST_PATH = '/integration/stock/transactions'


@dataclass(frozen=True)
class IngestResult:
    ok: bool
    transaction_id: int | None = None
    duplicate: bool = False
    error: str | None = None
    retryable: bool = True     # 4xx(입력·인증 문제)는 재시도해도 소용없다


def is_enabled() -> bool:
    """연동 토큰이 설정돼 있는가. 없으면 아웃박스에 넣되 전송하지 않는다."""
    return bool(os.getenv('GAGEBU_INGEST_TOKEN', '').strip())


def send_transaction(idempotency_key: str, source: str, type_val: str,
                     amount: int, title: str, date_str: str,
                     category_hint: str = '') -> IngestResult:
    """
    가계부에 거래 1건 기록. 멱등 — 같은 idempotency_key 재전송은 안전하다.

    account_book_id·member_id 는 **보내지 않는다** — 가계부가 토큰 행에서 정한다.
    """
    token = os.getenv('GAGEBU_INGEST_TOKEN', '').strip()
    if not token:
        return IngestResult(ok=False, error='GAGEBU_INGEST_TOKEN 미설정', retryable=False)

    payload: dict[str, Any] = {
        'idempotency_key': idempotency_key,
        'source': source,
        'type': type_val,
        'amount': str(amount),
        'title': title,
        'date': date_str,
    }
    if category_hint:
        payload['category_hint'] = category_hint

    try:
        resp = requests.post(f'{BASE_URL}{_INGEST_PATH}', json=payload,
                             headers={'Authorization': f'Bearer {token}'},
                             timeout=_TIMEOUT)
    except requests.RequestException as e:
        # 가계부가 안 떠 있거나 네트워크 문제 — 디스패처가 다음 주기에 다시 집는다.
        logger.warning(f'[gagebu] 전송 실패(재시도 대상) {source} {idempotency_key[:12]}: {e}')
        return IngestResult(ok=False, error=f'{type(e).__name__}: {e}', retryable=True)

    if resp.status_code in (200, 201):
        try:
            body = resp.json()
        except ValueError:
            return IngestResult(ok=False, error='응답이 JSON 이 아님', retryable=True)
        return IngestResult(ok=True,
                            transaction_id=body.get('transaction_id'),
                            duplicate=bool(body.get('duplicate')))

    # 4xx 는 입력·인증 문제라 같은 요청을 재시도해도 결과가 같다. 무한 재시도 금지.
    retryable = resp.status_code >= 500 or resp.status_code == 429
    try:
        err = resp.json().get('error', resp.text[:200])
    except ValueError:
        err = resp.text[:200]
    level = logger.warning if retryable else logger.error
    level(f'[gagebu] {resp.status_code} {source} {idempotency_key[:12]}: {err}')
    return IngestResult(ok=False, error=f'HTTP {resp.status_code}: {err}',
                        retryable=retryable)
