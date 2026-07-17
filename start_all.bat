@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
title Stock Git (copy) - Web only :5099

cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM ====================================================================
REM  복사본 웹 전용 런처 (포트 5099)
REM  [중요] 5001(원본)은 절대 건드리지 않는다. kill 코드 없음.
REM         스케줄러 OFF / 수집기·워치독·모니터 미기동 → 원본과 자원 충돌 방지.
REM         (같은 .env / MySQL / 키움 단일 로그인 / 5100 수집기를 공유하므로,
REM          복사본은 웹 UI만 5099에서 따로 띄우고 원본 자원을 그대로 재사용한다.)
REM
REM  [2026-07-17] DB를 expense_tracker → stock_stack 으로 이관했으나 원본·복사본이
REM  여전히 같은 DB를 본다. 따라서 스케줄러 OFF 규칙은 그대로 유지해야 한다.
REM  주의: .env 에는 RUN_SCHEDULER=true 가 들어 있어, 이 bat 을 거치지 않고
REM  `python app.py` 로 직접 띄우면 원본과 이중 발사된다(알림·백업 중복).
REM  복사본에서 산출물을 내려면 스케줄러 대신 파이프라인을 온디맨드로 실행할 것:
REM    python -m XGBoost_v2.collect_v2 --top 200
REM    python -m XGBoost_v2.daily_recommend
REM ====================================================================

REM 64bit venv (FastAPI)
set "VENV64=d:\expense_tracker\.venv64\Scripts\python.exe"
if not exist "%VENV64%" (
    echo [ERROR] 64bit venv python not found: %VENV64%
    pause
    exit /b 1
)

REM 원본과 중복 실행 방지: 스케줄러는 끈다 (알림/작업 중복 발사 방지)
set RUN_SCHEDULER=false

echo ===================================================
echo  Stock Git (copy) - Web only
echo  Port    : 5099  (원본 5001 은 건드리지 않음)
echo  Scheduler: OFF
echo  Collector: 원본 5100 재사용 (별도 기동 안 함)
echo ===================================================
echo.
echo Killing any existing process on port 5099...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5099 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

set PORT=5099
"%VENV64%" -m uvicorn app:app --host 127.0.0.1 --port 5099

pause
