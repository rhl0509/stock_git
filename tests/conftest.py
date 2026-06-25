"""pytest 공용 픽스처 — TestClient + 임시 사용자.

실행: d:\\expense_tracker\\.venv64\\Scripts\\python.exe -m pytest tests -q
(실DB를 사용하므로 MySQL이 떠 있어야 한다. 테스트 데이터는 자동 정리.)
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ['RUN_SCHEDULER'] = 'false'   # 테스트에서 스케줄러/잡 기동 금지

from fastapi.testclient import TestClient  # noqa: E402

TEST_USER = "pytest_smoke_user"
TEST_PW   = "pytest-pass-1234"


@pytest.fixture(scope="session")
def client():
    import app as appmod
    # lifespan(startup) 실행을 위해 컨텍스트 매니저 사용
    with TestClient(appmod.app) as c:
        yield c


def _cleanup_test_user():
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM members WHERE user_id=%s", (TEST_USER,))
            row = cur.fetchone()
            if row:
                uid = row['id']
                for sql in (
                    "DELETE FROM dividend_records WHERE user_no=%s",
                    "DELETE FROM price_alerts WHERE user_no=%s",
                    "DELETE FROM stock_holdings WHERE member_id=%s",
                    "DELETE FROM stock_transactions WHERE member_id=%s",
                    "DELETE FROM paper_positions WHERE user_no=%s",
                    "DELETE FROM paper_log WHERE user_no=%s",
                    "DELETE FROM paper_account WHERE user_no=%s",
                    "DELETE FROM watchlist_items WHERE user_no=%s",
                    "DELETE FROM watchlist_groups WHERE user_no=%s",
                    "DELETE FROM members WHERE id=%s",
                ):
                    try:
                        cur.execute(sql, (uid,))
                    except Exception:
                        pass
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session")
def auth_client(client):
    """임시 계정으로 로그인된 클라이언트. 세션 종료 시 데이터 정리."""
    _cleanup_test_user()  # 이전 실행 잔재 제거
    r = client.post("/auth/register", json={
        "user_id": TEST_USER, "password": TEST_PW,
        "name": "pytest", "email": "pytest@smoke.local",
    })
    assert r.status_code == 201, f"register 실패: {r.text}"
    r = client.post("/auth/login", json={"user_id": TEST_USER, "password": TEST_PW})
    assert r.status_code == 200, f"login 실패: {r.text}"
    yield client
    _cleanup_test_user()
