@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
title Stock Git - Web :8030

cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM ====================================================================
REM  stock_git 런처 (포트 8030, 독립 운영)
REM  [중요] 8020(원본 D:\stock_tracker)은 절대 건드리지 않는다. kill 코드 없음.
REM
REM  [2026-07-29] DB 를 stock_stack 에서 stock_git 으로 분리했다. 원본과 테이블을
REM  공유하지 않으므로 스케줄러를 켜도 DB 쪽 이중 기록은 없다. 이 bat 의
REM  RUN_SCHEDULER=false 강제도 함께 걷어냈다 — 이제 .env 값(true)이 그대로 먹고,
REM  `python app.py` 로 직접 띄워도 이 bat 과 동작이 같다.
REM
REM  [남은 주의] DB 는 갈라졌지만 알림 수신자(텔레그램/카카오)는 그대로 하나다.
REM  원본 8020 의 스케줄러가 켜져 있으면 아침뉴스·공시·가격 알림이 두 번 온다.
REM  둘 다 상시 운용하려면 한쪽 스케줄러를 끄거나 수신 채널을 분리할 것.
REM
REM  수집기: stock_git 은 KIS REST 전용이라 32bit 키움 콜렉터에 의존하지 않는다
REM  (kiwoom_client.py 참고). 계좌·조건검색 등 OCX 전용 기능은 미제공.
REM ====================================================================

REM 64bit venv (FastAPI)
set "VENV64=d:\expense_tracker\.venv64\Scripts\python.exe"
if not exist "%VENV64%" (
    echo [ERROR] 64bit venv python not found: %VENV64%
    pause
    exit /b 1
)

REM 스케줄러는 .env 의 RUN_SCHEDULER 가 결정한다(여기서 덮지 않는다).

echo ===================================================
echo  Stock Git - Web :8030 (독립 운영)
echo  DB      : stock_git  (원본 8020 의 stock_stack 과 분리)
echo  Port    : 8030  (원본 8020 은 건드리지 않음)
echo  Scheduler: .env RUN_SCHEDULER 따름
echo ===================================================
echo.
echo Killing any existing process on port 8030...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8030 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

set PORT=8030
"%VENV64%" -m uvicorn app:app --host 127.0.0.1 --port 8030

pause
