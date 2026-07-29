"""핵심 회귀 스모크 테스트 — 이 세션에서 잡았던 버그들의 재발 방지."""
import inspect

import pytest


# ─────────────────────────────────────────────────────────────────
# 1. 인증 커버리지: 의존성도 내부 세션체크도 없는 라우트 금지
# ─────────────────────────────────────────────────────────────────
AUTH_FNS  = {"require_login", "api_require_login", "require_login_smart", "require_owner"}
# 세션이 아닌 자체 인증(서명/일회용 토큰)으로 보호되는 의도된 공개 엔드포인트.
PUBLIC_OK = {"/login", "/register", "/find-account", "/", "/health", "/{full_path:path}",
             "/auth/login", "/auth/register", "/auth/logout", "/auth/find-account",
             "/auth/find-id", "/auth/find-password", "/auth/me", "/auth/api/me",
             "/auth/update-profile", "/auth/profile", "/auth/change-password",
             "/auth/reset-password",      # 일회용 재설정 토큰(해시+만료) + IP 레이트리밋
             "/api/credits/webhook"}      # PortOne 웹훅 서명 검증


def test_no_unprotected_routes(client):
    import app as appmod
    from fastapi.routing import APIRoute

    def has_auth(route):
        def walk(dep):
            fn = getattr(dep.call, "__name__", "") if dep.call else ""
            return fn in AUTH_FNS or any(walk(d) for d in dep.dependencies)
        return walk(route.dependant)

    naked = []
    for r in appmod.app.routes:
        if not isinstance(r, APIRoute) or r.path in PUBLIC_OK:
            continue
        if not has_auth(r):
            src = inspect.getsource(r.endpoint)
            if "get_login_user" not in src and "request.session" not in src:
                naked.append(f"{sorted(r.methods or [])} {r.path}")
    assert not naked, f"무방비 라우트 발견: {naked}"


# ─────────────────────────────────────────────────────────────────
# 2. 비인증 차단: 민감 엔드포인트 샘플
# ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/api/kiwoom/info/005930",
    "/api/paper_trading/summary",
    "/api/price_alerts",
    "/recommend/json",
    "/api/trade/summary",
    "/api/risk/dashboard",
])
def test_unauth_blocked(client, path):
    r = client.get(path, headers={"Accept": "application/json"},
                   follow_redirects=False)
    assert r.status_code in (401, 302), f"{path} → {r.status_code}"


def test_unknown_api_returns_404_json(client):
    r = client.get("/api/this-does-not-exist", headers={"Accept": "application/json"})
    assert r.status_code == 404
    assert "error" in r.json()


# ─────────────────────────────────────────────────────────────────
# 3. 인증 플로우 + 프로필/비밀번호 변경 (MyPage 계약)
# ─────────────────────────────────────────────────────────────────
def test_profile_contract(auth_client):
    r = auth_client.get("/auth/profile")
    assert r.status_code == 200
    assert r.json()["user_id"] == "pytest_smoke_user"

    r = auth_client.put("/auth/profile", json={"name": "pytest2", "email": "pytest@smoke.local",
                                                "phone": "010-1234-5678"})
    assert r.status_code == 200

    # 빈 이메일 덮어쓰기 거부 (과거 버그)
    r = auth_client.put("/auth/profile", json={"name": "pytest2", "email": ""})
    assert r.status_code == 400


def test_change_password_wrong_current(auth_client):
    r = auth_client.put("/auth/change-password",
                        json={"current_password": "wrong", "new_password": "newpass1234"})
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────
# 4. Decimal 직렬화 회귀 (배당)
# ─────────────────────────────────────────────────────────────────
def test_dividend_decimal_roundtrip(auth_client):
    r = auth_client.post("/api/dividend", json={
        "stock_code": "005930", "stock_name": "삼성전자",
        "ex_div_date": "2026-03-30", "pay_date": "2026-04-29",
        "dividend_per_share": 372.5, "quantity": 10, "total_amount": 3725,
    })
    assert r.status_code == 200, r.text
    r = auth_client.get("/api/dividend")
    assert r.status_code == 200, f"Decimal 직렬화 회귀: {r.text[:200]}"
    rec = r.json()["records"][0]
    assert rec["dividend_per_share"] == 372.5
    r = auth_client.get("/api/dividend/summary")
    assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────
# 5. 세금 계산기 (Tax.jsx 계약)
# ─────────────────────────────────────────────────────────────────
def test_tax_calculate(auth_client):
    r = auth_client.post("/api/tax/calculate", json={
        "buy_price": 70000, "sell_price": 80000, "quantity": 100,
        "is_major_shareholder": False,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["buy_total"] == 7_000_000
    assert d["sell_total"] == 8_000_000
    assert d["transaction_tax"] == 16_000           # 매도 0.20%
    assert d["capital_gains_tax"] == 0              # 소액주주 비과세
    assert 0 < d["net_profit"] < 1_000_000


# ─────────────────────────────────────────────────────────────────
# 6. 수동 모의매매 (PaperTrading.jsx 계약)
# ─────────────────────────────────────────────────────────────────
def test_paper_trading_lifecycle(auth_client):
    r = auth_client.post("/api/paper_trading/reset")
    assert r.status_code == 200 and r.json()["cash"] == 10_000_000

    # 매수
    r = auth_client.post("/api/paper_trading/buy",
                         json={"code": "005930", "name": "삼성전자", "price": 70000, "quantity": 10})
    assert r.status_code == 200, r.text
    port = auth_client.get("/api/paper_trading/portfolio").json()
    assert port["account"]["cash"] == 10_000_000 - 700_000
    assert port["positions"][0]["quantity"] == 10

    # 예수금 초과 매수 거부
    r = auth_client.post("/api/paper_trading/buy",
                         json={"code": "000660", "name": "SK하이닉스", "price": 2_000_000, "quantity": 100})
    assert r.status_code == 400

    # 보유 초과 매도 거부
    r = auth_client.post("/api/paper_trading/sell",
                         json={"code": "005930", "name": "삼성전자", "price": 71000, "quantity": 999})
    assert r.status_code == 400

    # 전량 매도 → 포지션 소멸
    r = auth_client.post("/api/paper_trading/sell",
                         json={"code": "005930", "name": "삼성전자", "price": 71000, "quantity": 10})
    assert r.status_code == 200
    port = auth_client.get("/api/paper_trading/portfolio").json()
    assert port["positions"] == []
    assert port["account"]["cash"] == 10_000_000 + 10_000   # +1만원 익절

    logs = auth_client.get("/api/paper_trading/log").json()["logs"]
    assert len(logs) == 2


# ─────────────────────────────────────────────────────────────────
# 7. 백테스트 코드 검증 (경로 탈출 차단)
# ─────────────────────────────────────────────────────────────────
def test_backtest_code_validation(auth_client):
    r = auth_client.post("/api/backtest/run",
                         json={"code": "../../../etc/passwd", "strategy": "ml"})
    assert r.status_code == 404   # 검증 실패 → 데이터 없음 처리


# ─────────────────────────────────────────────────────────────────
# 9. price_alerts 사용자 격리
# ─────────────────────────────────────────────────────────────────
def test_price_alert_user_scoped(auth_client):
    r = auth_client.post("/api/price_alerts",
                         json={"code": "005930", "name": "삼성전자", "target_price": 99999})
    assert r.status_code == 200
    alerts = auth_client.get("/api/price_alerts").json()["alerts"]
    assert all('user_no' in a for a in alerts)
    assert len({a['user_no'] for a in alerts}) == 1   # 전부 내 것


# ─────────────────────────────────────────────────────────────────
# 10. 실패 응답 본문이 로그·DB 에 평문 자격증명을 남기지 않는다
#     (로그가 회전 파일로 영속되면서 콘솔 휘발 전제가 깨졌다)
# ─────────────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, text):
        self.text = text


def test_safe_body_masks_credentials():
    from notify.send import _safe_body

    body = ('{"error":"invalid_grant","refresh_token":"RT-abcdef123456",'
            '"client_secret":"CS-secret999","access_token":"AT-zzz111"}')
    out = _safe_body(_FakeResp(body))

    for leaked in ("RT-abcdef123456", "CS-secret999", "AT-zzz111"):
        assert leaked not in out, f"자격증명 유출: {leaked} in {out}"
    assert "invalid_grant" in out          # 진단에 필요한 오류 코드는 남긴다
    assert out.count("***") == 3

    # form-urlencoded 되비침도 가린다
    out2 = _safe_body(_FakeResp("grant_type=refresh_token&client_secret=CS-x9&client_id=CID-42"))
    assert "CS-x9" not in out2 and "CID-42" not in out2

    # 오류 코드는 자격증명이 아니므로 남아야 한다(과잉 마스킹 방지)
    out3 = _safe_body(_FakeResp('{"msg":"token not exist","code":-401}'))
    assert "-401" in out3


def test_safe_body_truncates_and_tolerates_empty():
    from notify.send import _safe_body

    assert len(_safe_body(_FakeResp("A" * 5000))) == 200
    assert _safe_body(_FakeResp("")) == ""
    assert _safe_body(_FakeResp(None)) == ""
