"""
routes/alert_config.py — 알림 설정 UI + API.
"""
import json
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Body
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from templates_config import render

router = APIRouter(dependencies=[Depends(require_login_smart)])

CONFIG_PATH = Path(__file__).parent.parent / "XGBoost_v2" / "model" / "alert_config.json"

DEFAULTS = {
    "morning_brief": {
        "enabled": True,
        "show_triple": True,
        "show_daily": True,
        "show_short": True,
        "show_swing": True,
        "max_picks_per_cat": 3,
        "show_macro": True,
    },
    "thresholds": {
        "daily_min_conf": 0.55,
        "short_min_conf": 0.55,
        "swing_min_conf": 0.55,
        "triple_min_combined": 0.55,
    },
    "errors": {
        "notify_train_error": True,
        "notify_recommend_error": True,
        "notify_incremental_error": True,
    },
    "closing_brief": {
        "enabled": True,
        "show_paper_summary": True,
    },
}


def _load() -> dict:
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            merged = json.loads(json.dumps(DEFAULTS))
            for section, vals in saved.items():
                if section in merged and isinstance(vals, dict):
                    merged[section].update(vals)
                else:
                    merged[section] = vals
            return merged
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULTS))


def _save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/alert_config")
def alert_config_page(request: Request):
    return render(request, "stock/alert_config.html")


@router.get("/api/alert_config")
def api_get():
    return _load()


@router.post("/api/alert_config")
def api_save(body: dict = Body(default=None)):
    if not body or not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)
    _save(body)
    return {"ok": True}


# ── 카카오 토큰 관리 (React AlertConfig.jsx 계약) ──

@router.get("/api/alert_config/kakao_status")
def kakao_status():
    """저장된 카카오 토큰 존재 여부 + 앞 8자 미리보기."""
    from database.db_connection import get_db_connection
    tokens = []
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT `key`, `value`, updated_at FROM app_settings "
                "WHERE `key` IN ('KAKAO_ACCESS_TOKEN','KAKAO_REFRESH_TOKEN')"
            )
            for r in cur.fetchall():
                tokens.append({
                    'key': r['key'],
                    'preview': (r['value'] or '')[:8],
                    'updated_at': r['updated_at'].strftime('%Y-%m-%d %H:%M') if r['updated_at'] else None,
                })
    except Exception:
        pass  # app_settings 미생성 시 빈 목록
    finally:
        conn.close()
    return {"ok": True, "tokens": tokens}


@router.post("/api/alert_config/kakao_token")
def kakao_token_save(body: dict = Body(default={})):
    """카카오 access/refresh 토큰 수동 등록 (notify.send 저장 로직 재사용)."""
    access  = (body.get('access_token') or '').strip()
    refresh = (body.get('refresh_token') or '').strip()
    if not access and not refresh:
        return JSONResponse({"ok": False, "error": "토큰을 입력하세요."}, status_code=400)
    # 미리보기 값(…포함)이 그대로 다시 제출된 경우는 변경 없음으로 간주
    from notify.send import _save_token
    saved = []
    if access and '...' not in access:
        _save_token('KAKAO_ACCESS_TOKEN', access)
        saved.append('access')
    if refresh and '...' not in refresh:
        _save_token('KAKAO_REFRESH_TOKEN', refresh)
        saved.append('refresh')
    return {"ok": True, "saved": saved}
