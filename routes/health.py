"""
routes/health.py — 서버 건강 체크 엔드포인트.

GET /health
  DB, Kiwoom 콜렉터, ML 모델 상태를 JSON으로 반환.
  모니터링 도구에서 인증 없이 호출 가능.
"""
import logging
import os
from datetime import datetime
from pathlib import Path

import requests as _requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "XGBoost_v2" / "model"
KIWOOM_PORT = os.getenv("KIWOOM_COLLECTOR_PORT", "5100")


@router.get("/health")
def health_check():
    components = {}
    all_ok = True

    # ── DB ──────────────────────────────────────────────────
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        components["db"] = {"ok": True}
    except Exception as e:
        components["db"] = {"ok": False, "error": type(e).__name__}
        all_ok = False

    # ── Kiwoom 32비트 콜렉터 ────────────────────────────────
    try:
        r = _requests.get(
            f"http://127.0.0.1:{KIWOOM_PORT}/status", timeout=3
        )
        data = r.json() if r.status_code == 200 else {}
        components["kiwoom"] = {
            "ok": r.status_code == 200,
            "logged_in": data.get("connected", False),
            "login_state": data.get("state"),
        }
    except Exception as e:
        components["kiwoom"] = {"ok": False, "error": type(e).__name__}

    # ── ML 모델 파일 ────────────────────────────────────────
    try:
        model_files = list(MODEL_DIR.glob("xgb_v2_*.json"))
        report_path = MODEL_DIR / "train_report_v2.json"
        trained_at = None
        if report_path.exists():
            import json
            rpt = json.loads(report_path.read_text(encoding="utf-8"))
            trained_at = rpt.get("trained_at", "")[:16]

        components["ml_model"] = {
            "ok": len(model_files) > 0,
            "model_count": len(model_files),
            "trained_at": trained_at,
        }
        if len(model_files) == 0:
            all_ok = False
    except Exception as e:
        components["ml_model"] = {"ok": False, "error": type(e).__name__}
        all_ok = False

    # ── 디스크 공간 ─────────────────────────────────────────
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        free_gb = round(free / (1024 ** 3), 1)
        components["disk"] = {
            "ok": free_gb > 1.0,
            "free_gb": free_gb,
            "total_gb": round(total / (1024 ** 3), 1),
        }
        if free_gb <= 1.0:
            all_ok = False
    except Exception as e:
        components["disk"] = {"ok": False, "error": type(e).__name__}

    result = {
        "ok": all_ok,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "components": components,
    }
    return JSONResponse(result, status_code=200 if all_ok else 503)
