"""
routes/health.py — 서버 건강 체크 엔드포인트.

GET /health
  DB, 시세 소스(KIS), ML 모델 상태를 JSON으로 반환.
  모니터링 도구에서 인증 없이 호출 가능.
"""
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "XGBoost_v2" / "model"


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

    # ── 시세 소스 (KIS REST) ────────────────────────────────
    try:
        from kiwoom_client import kiwoom
        ready = kiwoom.market_data_ready()
        components["market_data"] = {"ok": ready, "source": "KIS" if ready else "NONE"}
    except Exception as e:
        components["market_data"] = {"ok": False, "error": type(e).__name__}

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
