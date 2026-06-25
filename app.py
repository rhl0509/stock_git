import sys
import os
import logging

os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('app')

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import Config
from templates_config import render
from routes.utils import require_login, LoginRequired, ApiLoginRequired

# ── 라우터 import ──
from routes.auth import router as auth_router
from routes.kiwoom import router as kiwoom_router
from routes.stock_holdings import router as stock_holdings_router
from routes.kr_stocks import router as kr_stocks_router, sync_kr_stocks
from routes.stock_filter import router as stock_filter_router
from routes.stock_api import router as stock_api_router
from routes.stock_ml import router as stock_ml_router
from routes.recommend import router as recommend_router
from routes.stock_data import router as stock_data_router
from routes.backtest import router as backtest_router
from routes.train_report import router as train_report_router
from routes.paper_trading import router as paper_trading_router
from routes.alert_config import router as alert_config_router
from routes.portfolio_opt import router as portfolio_opt_router
from routes.quant import router as quant_router
from routes.sector import router as sector_router
from routes.pipeline import router as pipeline_router, _ensure_table as _ensure_pipeline_table
from routes.financial import router as financial_router
from routes.health import router as health_router
from routes.notify_history import router as notify_history_router
from routes.tax import router as tax_router
from routes.news import router as news_router
from routes.company_research import router as company_research_router
from routes.morning_news import router as morning_news_router, _ensure_table as _ensure_morning_news_table, crawl_and_notify as _morning_news_crawl
from routes.dart_alert import router as dart_alert_router, _ensure_table as _ensure_dart_alert_table, check_and_notify as _dart_check_notify
from routes.macro_dashboard import router as macro_dashboard_router
from routes.price_alert import router as price_alert_router, _ensure_table as _ensure_price_alert_table, check_price_alerts as _price_alert_check
from routes.portfolio_perf import router as portfolio_perf_router
from routes.reports import router as reports_router
from routes.trade_stats import router as trade_stats_router
from routes.agent_dashboard import router as agent_dashboard_router
from routes.dividend import router as dividend_router
from routes.watchlist import router as watchlist_router
from routes.screener import router as screener_router
from routes.rebalance import router as rebalance_router
from routes.risk import router as risk_router
from routes.workflows import router as workflows_router
from routes.credits import router as credits_router, _ensure_table as _ensure_credits_table
from routes.chat import router as chat_router
from routes.stock_advisor import router as stock_advisor_router
from routes.recommend_pass import router as recommend_pass_router, _ensure_table as _ensure_recommend_pass_table
from database.db_connection import get_db_connection

@asynccontextmanager
async def _lifespan(app: FastAPI):
    _startup()
    yield


app = FastAPI(lifespan=_lifespan)

# ── 미들웨어 ──
# https_only=False: 현재 로컬 HTTP 운영. 외부 노출(리버스 프록시/HTTPS) 시 True로 변경할 것.
app.add_middleware(
    SessionMiddleware,
    secret_key=Config.SECRET_KEY,
    max_age=60 * 60 * 24 * 7,  # 7일
    same_site="lax",
    https_only=False,
)

# ── 정적 파일 ──
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ── React SPA 에셋 (/assets/... → static/spa/assets/) ──
_SPA_ASSETS = "static/spa/assets"
if os.path.isdir(_SPA_ASSETS):
    app.mount("/assets", StaticFiles(directory=_SPA_ASSETS), name="spa_assets")

# ── 예외 핸들러 ──
@app.exception_handler(LoginRequired)
async def _login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url="/login", status_code=302)

@app.exception_handler(ApiLoginRequired)
async def _api_login_required_handler(request: Request, exc: ApiLoginRequired):
    return JSONResponse({"error": "로그인이 필요합니다."}, status_code=401)

@app.exception_handler(404)
async def _not_found_handler(request: Request, exc):
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": "페이지를 찾을 수 없습니다."}, status_code=404)
    return render(request, "error.html", {"code": 404, "message": "페이지를 찾을 수 없습니다."})

@app.exception_handler(500)
async def _internal_error_handler(request: Request, exc):
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": "서버 내부 에러가 발생했습니다."}, status_code=500)
    return render(request, "error.html", {"code": 500, "message": "서버 내부 에러가 발생했습니다."})

# ── 라우터 등록 ──
app.include_router(auth_router, prefix="/auth")
app.include_router(kiwoom_router, prefix="/api")
app.include_router(stock_holdings_router)
app.include_router(kr_stocks_router)
app.include_router(stock_filter_router)
app.include_router(stock_api_router)
app.include_router(stock_ml_router)
app.include_router(recommend_router)
app.include_router(stock_data_router)
app.include_router(backtest_router)
app.include_router(train_report_router)
app.include_router(paper_trading_router)
app.include_router(alert_config_router)
app.include_router(portfolio_opt_router)
app.include_router(quant_router)
app.include_router(sector_router)
app.include_router(pipeline_router)
app.include_router(financial_router)
app.include_router(health_router)
app.include_router(notify_history_router)
app.include_router(tax_router)
app.include_router(news_router)
app.include_router(company_research_router)
app.include_router(morning_news_router)
app.include_router(dart_alert_router)
app.include_router(macro_dashboard_router)
app.include_router(price_alert_router)
app.include_router(portfolio_perf_router)
app.include_router(reports_router)
app.include_router(trade_stats_router)
app.include_router(agent_dashboard_router)
app.include_router(dividend_router)
app.include_router(watchlist_router)
app.include_router(screener_router)
app.include_router(rebalance_router)
app.include_router(risk_router)
app.include_router(workflows_router)
app.include_router(credits_router)
app.include_router(chat_router)
app.include_router(stock_advisor_router)
app.include_router(recommend_pass_router)

# =========================================================
# ── 페이지 라우트 ──
# =========================================================

@app.get("/login")
async def login_page(request: Request):
    if "user_no" in request.session:
        return RedirectResponse(url="/stock_live", status_code=302)
    return render(request, "auth/login.html")

@app.get("/register")
async def register_page(request: Request):
    return render(request, "auth/register.html")

@app.get("/")
async def index(request: Request, _=Depends(require_login)):
    return RedirectResponse(url="/stock_live", status_code=302)

@app.get("/stock_dashboard")
async def stock_dashboard(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_dashboard.html")

@app.get("/stock_live")
async def stock_live_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_live.html")

@app.get("/stock_detail")
async def stock_detail(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_detail.html")

@app.get("/stock_compare")
async def stock_compare(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_compare.html")

@app.get("/stock_compare_v2")
async def stock_compare_v2(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_compare_v2.html")

@app.get("/stock_portfolio_kr")
async def stock_portfolio_kr(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_portfolio_kr.html")

@app.get("/stock_portfolio")
async def stock_portfolio(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_portfolio.html")

@app.get("/stock_filter")
async def stock_filter_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_filter.html")

@app.get("/stock_kiwoom_filter")
async def stock_kiwoom_filter_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_kiwoom_filter.html")

@app.get("/stock_theme_filter")
async def stock_theme_filter_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/stock_theme_filter.html")

@app.get("/stock_recommend_history")
async def stock_recommend_history_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/recommend_history.html")

@app.get("/stock_ai_performance")
async def stock_ai_performance_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/ai_performance.html")

@app.get("/my-page")
async def my_page(request: Request, _=Depends(require_login)):
    return render(request, "stock/my_page.html")

@app.get("/find-account")
async def find_account_page(request: Request):
    return render(request, "auth/find_account.html")

# =========================================================
# ── 시작 이벤트 ──
# =========================================================

def _startup():
    # KR 종목 DB 초기화
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as cnt FROM kr_stocks")
            cnt = cursor.fetchone()['cnt']
        conn.close()
        if cnt == 0:
            logger.info("[KR_STOCKS] DB 비어있음 → 자동 동기화 시작...")
            sync_kr_stocks()
    except Exception as e:
        logger.error(f"[KR_STOCKS] 초기화 확인 실패: {e}")

    for label, fn in (
        ("PIPELINE",     _ensure_pipeline_table),
        ("MORNING_NEWS", _ensure_morning_news_table),
        ("DART_ALERT",   _ensure_dart_alert_table),
        ("PRICE_ALERT",  _ensure_price_alert_table),
        ("CREDITS",      _ensure_credits_table),
        ("RECOMMEND_PASS", _ensure_recommend_pass_table),
    ):
        try:
            fn()
        except Exception as e:
            logger.error(f"[{label}] 테이블 초기화 실패: {e}")

    try:
        from notify.send import _ensure_table as _ensure_notify_table
        _ensure_notify_table()
    except Exception as e:
        logger.error(f"[NOTIFY] 테이블 초기화 실패: {e}")

    try:
        from notify.send import migrate_tokens_to_db
        migrate_tokens_to_db()
    except Exception:
        pass

    # ── 스케줄러 ──
    # 주의: 웹 프로세스 내장 스케줄러. uvicorn 워커를 늘리면 작업이 중복 실행되므로
    # 멀티 워커 운영 시 RUN_SCHEDULER=false로 끄고 별도 프로세스로 분리할 것.
    scheduler = None
    if os.getenv('RUN_SCHEDULER', 'true').lower() != 'true':
        logger.info("[SCHEDULER] RUN_SCHEDULER=false → 스케줄러 비활성화")
    else:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            def _train_job():
                import subprocess
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'XGBoost_v2.train_v2', '--skip-optuna', '--no-pit'],
                        capture_output=True, text=True, timeout=7200
                    )
                    status = '완료' if result.returncode == 0 else f'실패(code={result.returncode})'
                    logger.info(f"[SCHEDULER] 모델 재학습 {status}")
                    try:
                        from notify.send import send_message_to_self
                        send_message_to_self(f'🤖 모델 재학습 {status}\n매주 일요일 02:00 자동 실행')
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"[SCHEDULER] 모델 재학습 오류: {e}")

            def _daily_recommend_job():
                try:
                    from XGBoost_v2.daily_recommend import run_daily, _load_ensemble
                    _load_ensemble.cache_clear()
                    run_daily(min_conf=0.20, save_txt=False, normalize=True)
                    _load_ensemble.cache_clear()
                    run_daily(min_conf=0.20, save_txt=False, normalize=False)
                    logger.info("[SCHEDULER] 데일리 추천 생성 완료 (상대+절대)")
                except Exception as e:
                    logger.error(f"[SCHEDULER] 데일리 추천 실패: {e}")

            scheduler = BackgroundScheduler(timezone='Asia/Seoul')
            scheduler.add_job(_morning_news_crawl, CronTrigger(hour=8, minute=40, timezone='Asia/Seoul'), id='morning_news', replace_existing=True)
            scheduler.add_job(_dart_check_notify, CronTrigger(day_of_week='mon-fri', hour='9-15', minute='0,30', timezone='Asia/Seoul'), id='dart_alert', replace_existing=True)
            scheduler.add_job(_daily_recommend_job, CronTrigger(hour=6, minute=30, timezone='Asia/Seoul'), id='daily_recommend', replace_existing=True)
            scheduler.add_job(_price_alert_check, CronTrigger(day_of_week='mon-fri', hour='9-15', minute='*/10', timezone='Asia/Seoul'), id='price_alert', replace_existing=True)
            scheduler.add_job(_train_job, CronTrigger(day_of_week='sun', hour=2, minute=0, timezone='Asia/Seoul'), id='weekly_train', replace_existing=True)

            # ── 자동화 잡 (키움동기화/배당기록/테마인덱스/모델백업/DB백업) ──
            try:
                from auto_jobs import register as _register_auto_jobs
                _register_auto_jobs(scheduler)
            except Exception as e:
                logger.error(f"[SCHEDULER] 자동화 잡 등록 실패: {e}")

            scheduler.start()
            logger.info("[SCHEDULER] 스케줄러 시작 완료")

            # ── 텔레그램 양방향 챗봇 (마켓 코파일럿) ──
            try:
                from notify.telegram_bot import start_polling as _start_tg_bot
                _start_tg_bot()
            except Exception as e:
                logger.error(f"[SCHEDULER] 텔레그램 챗봇 시작 실패: {e}")
        except Exception as e:
            scheduler = None
            logger.error(f"[SCHEDULER] 스케줄러 시작 실패: {e}")

    # ── 보고서 에이전트 ──
    try:
        from agent.db_migrate import run as _migrate_reports
        _migrate_reports()
    except Exception as e:
        logger.error(f"[REPORTS] DB 마이그레이션 실패: {e}")

    if scheduler is not None:
        try:
            from agent.scheduler import start as _start_report_scheduler
            # 기존 scheduler 인스턴스를 재사용해 APScheduler 인스턴스 중복 방지
            _start_report_scheduler(scheduler=scheduler)
        except Exception as e:
            logger.error(f"[REPORTS] 보고서 스케줄러 시작 실패: {e}")


# ── React SPA catch-all (반드시 모든 라우트 등록 뒤에 위치) ──
_SPA_INDEX = "static/spa/index.html"
if os.path.isfile(_SPA_INDEX):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str = ""):
        # 존재하지 않는 API 경로는 index.html 대신 404 JSON (디버깅 혼선 방지)
        if full_path.startswith(("api/", "auth/")):
            return JSONResponse({"error": "존재하지 않는 API 경로입니다."}, status_code=404)
        return FileResponse(_SPA_INDEX)


if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('PORT', '5001'))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=False)
