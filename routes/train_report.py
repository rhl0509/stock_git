"""
routes/train_report.py — 학습 리포트 페이지 + 데이터 API.
"""
import json
from pathlib import Path
from fastapi import APIRouter, Request, Depends
from routes.utils import require_login_smart
from fastapi.responses import JSONResponse
from templates_config import render

router = APIRouter(dependencies=[Depends(require_login_smart)])

MODEL_DIR = Path(__file__).parent.parent / "XGBoost_v2" / "model"


@router.get("/stock_train_report")
def train_report_page(request: Request):
    return render(request, "stock/train_report.html")


@router.get("/api/train_report")
@router.get("/api/train_report_data")
def train_report_data():
    report_path = MODEL_DIR / "train_report_v2.json"
    shap_path   = MODEL_DIR / "shap_importance_v2.json"

    if not report_path.exists():
        return JSONResponse({"ok": False, "error": "train_report_v2.json 없음 — 학습 필요"}, status_code=404)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    shap   = json.loads(shap_path.read_text(encoding="utf-8")) if shap_path.exists() else {}

    return {"ok": True, "report": report, "shap": shap}


@router.get("/api/ai_performance")
def ai_performance():
    history_path = MODEL_DIR / "ml_performance_history.json"
    report_path  = MODEL_DIR / "train_report_v2.json"

    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:
            history = []

    # 이력 파일이 없으면 현재 train_report_v2.json으로 1건 생성
    if not history and report_path.exists():
        try:
            r = json.loads(report_path.read_text(encoding="utf-8"))
            history = [{
                "trained_at": r.get("trained_at", ""),
                "n_tickers":  r.get("n_tickers", 0),
                "n_samples":  r.get("n_samples", 0),
                "n_features": r.get("n_features", 0),
                "labels": {
                    k: {"cv_auc": v.get("cv_auc"), "cv_acc": v.get("cv_acc"), "buy_ratio": v.get("buy_ratio")}
                    for k, v in r.get("labels", {}).items()
                },
            }]
        except Exception:
            pass

    if not history:
        return JSONResponse({"ok": False, "error": "성능 이력 없음 — 학습 필요"}, status_code=404)

    return {"ok": True, "history": history}
