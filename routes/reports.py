"""
routes/reports.py
=================
보고서 웹 대시보드 및 API.

  GET  /reports              — 보고서 목록 페이지 (HTML)
  GET  /reports/{id}         — 보고서 상세 페이지 (HTML)
  GET  /reports/json         — 보고서 목록 JSON
  GET  /reports/json/{id}    — 보고서 상세 JSON
  POST /reports/generate     — 수동 보고서 생성 (백그라운드)
  GET  /reports/schedule     — 스케줄 현황
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from routes.utils import require_login_smart

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_login_smart)], prefix="/reports", tags=["reports"])


# ─────────────────────────────────────────────────────────────────
# HTML 페이지
# ─────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def reports_page(request: Request):
    # 인증은 라우터 레벨 require_login_smart(:23)가 이미 건다. 예전엔 여기서
    # require_login(request) 를 await 없이 불러 코루틴 객체를 만들고 hasattr 검사가
    # 항상 False 라 죽은 코드였다(템플릿도 user 를 안 쓴다). 제거한다.
    from agent.store import get_reports
    from templates_config import templates

    daily   = get_reports("daily",   limit=7)
    weekly  = get_reports("weekly",  limit=4)
    monthly = get_reports("monthly", limit=6)

    return templates.TemplateResponse(
        "stock/reports.html",
        {
            "request": request,
            "daily":   daily,
            "weekly":  weekly,
            "monthly": monthly,
        },
    )


@router.get("/schedule", response_class=JSONResponse)
def api_schedule():
    try:
        from agent.scheduler import get_status
        return JSONResponse({"ok": True, "schedules": get_status()})
    except Exception as e:
        logger.error(f'[reports] {e}', exc_info=True)
        return JSONResponse({"ok": False, "error": '서버 오류가 발생했습니다.'})


@router.post("/generate")
def api_generate(
    request: Request,
    background_tasks: BackgroundTasks,
    report_type: str = Query(..., description="daily | weekly | monthly"),
):
    # 인증은 라우터 레벨(:23)이 건다. 아래 죽은 코드(await 없는 코루틴 + 항상-False
    # hasattr)를 제거했다.
    if report_type not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="report_type은 daily/weekly/monthly 중 하나")

    def _bg_run():
        try:
            if report_type == "daily":
                from agent.report_daily import run
            elif report_type == "weekly":
                from agent.report_weekly import run
            else:
                from agent.report_monthly import run
            result = run(send_kakao=True)
            logger.info(f"[reports/generate] 완료: {result}")
        except Exception as e:
            logger.error(f"[reports/generate] 실패: {e}", exc_info=True)

    background_tasks.add_task(_bg_run)
    return JSONResponse({"ok": True, "message": f"{report_type} 보고서 생성 중 (백그라운드)"})


@router.get("/latest")
def api_latest_report():
    """홈 위젯용 최신 보고서 요약 반환."""
    from agent.store import get_reports
    for rtype in ('daily', 'weekly', 'monthly'):
        rows = get_reports(rtype, limit=1)
        if rows:
            r = rows[0]
            return JSONResponse({'ok': True, 'report_type': r['report_type'],
                                 'report_date': str(r.get('report_date', '')),
                                 'title': r.get('title', ''), 'summary': r.get('summary', ''),
                                 'content': (r.get('content') or '')[:400]})
    return JSONResponse({'ok': False})


@router.get("/json")
def api_reports(
    report_type: Optional[str] = Query(None, description="daily | weekly | monthly"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    from agent.store import get_reports
    rows = get_reports(report_type, limit=limit, offset=offset)
    return JSONResponse({"ok": True, "reports": [_serialize(r) for r in rows]})


@router.get("/json/{report_id}")
def api_report_detail(report_id: int):
    from agent.store import get_report_by_id
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    return JSONResponse({"ok": True, "report": _serialize(report)})


# /{report_id}는 int 경로만 매칭되므로 /schedule, /generate, /json과 충돌 없음
@router.get("/{report_id}", response_class=HTMLResponse)
def report_detail_page(request: Request, report_id: int):
    # 인증은 라우터 레벨(:23)이 건다(위 죽은 코드 제거).
    from agent.store import get_report_by_id
    from templates_config import templates

    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")

    return templates.TemplateResponse(
        "stock/report_detail.html",
        {"request": request, "report": report},
    )


# ─────────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────────

def _serialize(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result
