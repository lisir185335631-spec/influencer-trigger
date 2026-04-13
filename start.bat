@echo off
REM ============================================================
REM  Influencer Trigger — One-click startup (Windows)
REM  Usage: double-click start.bat or run from cmd
REM ============================================================
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "SERVER_DIR=%SCRIPT_DIR%server"
set "CLIENT_DIR=%SCRIPT_DIR%client"

echo ==============================
echo  Influencer Trigger  startup
echo ==============================

REM ---- 1. Check .env ----
if not exist "%SERVER_DIR%\.env" (
    echo [WARN] server\.env not found. Copying from .env.example...
    copy "%SERVER_DIR%\.env.example" "%SERVER_DIR%\.env" >nul
    echo [WARN] Please edit server\.env before production use.
)

REM ---- 2. Ensure data directory ----
if not exist "%SERVER_DIR%\data" mkdir "%SERVER_DIR%\data"

REM ---- 3. Python virtualenv & dependencies ----
if not exist "%SERVER_DIR%\.venv" (
    echo [INFO] Creating Python virtualenv...
    python -m venv "%SERVER_DIR%\.venv"
)

call "%SERVER_DIR%\.venv\Scripts\activate.bat"
echo [INFO] Installing Python dependencies...
pip install -q -r "%SERVER_DIR%\requirements.txt"

REM ---- 4. Start Redis (optional, skip if not installed) ----
where redis-server >nul 2>&1
if %errorlevel% == 0 (
    echo [INFO] Starting Redis...
    start /b redis-server --loglevel warning
    timeout /t 2 /nobreak >nul
) else (
    echo [INFO] Redis not found - rate limiting will use in-memory fallback.
)

REM ---- 5. Start FastAPI backend ----
echo [INFO] Starting FastAPI backend on port 8000...
cd /d "%SERVER_DIR%"
start /b cmd /c "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > %TEMP%\influencer-backend.log 2>&1"
echo [INFO] Backend starting...

REM Wait a few seconds for backend to start
timeout /t 5 /nobreak >nul

REM ---- 6. Start Frontend dev server ----
echo [INFO] Starting frontend dev server on port 3000...
cd /d "%CLIENT_DIR%"
call npm ci --silent
start /b cmd /c "npm run dev > %TEMP%\influencer-frontend.log 2>&1"
echo [INFO] Frontend starting...

echo.
echo ==============================
echo  Services starting:
echo   Backend:  http://localhost:8000
echo   API docs: http://localhost:8000/docs
echo   Frontend: http://localhost:3000
echo.
echo  Logs:
echo   Backend:  %TEMP%\influencer-backend.log
echo   Frontend: %TEMP%\influencer-frontend.log
echo ==============================
echo.
pause
