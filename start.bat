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
echo [INFO] Starting FastAPI backend on port 6002...
cd /d "%SERVER_DIR%"
start /b cmd /c "python -m uvicorn app.main:app --host 0.0.0.0 --port 6002 > %TEMP%\influencer-backend.log 2>&1"

REM Wait for backend to be ready
echo [INFO] Waiting for backend...
set "BACKEND_READY=0"
for /L %%i in (1,1,30) do (
    if !BACKEND_READY! == 0 (
        curl -sf http://localhost:6002/api/health >nul 2>&1
        if !errorlevel! == 0 (
            set "BACKEND_READY=1"
            echo [OK] Backend is ready.
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
if !BACKEND_READY! == 0 (
    echo [WARN] Backend did not respond within 30s, continuing anyway...
)

REM ---- 6. Start Frontend dev server ----
echo [INFO] Starting frontend dev server on port 6001...
cd /d "%CLIENT_DIR%"
call npm ci --silent
start /b cmd /c "npm run dev > %TEMP%\influencer-frontend.log 2>&1"

REM Wait for frontend to be ready
echo [INFO] Waiting for frontend...
set "FRONTEND_READY=0"
for /L %%i in (1,1,30) do (
    if !FRONTEND_READY! == 0 (
        curl -sf http://localhost:6001 >nul 2>&1
        if !errorlevel! == 0 (
            set "FRONTEND_READY=1"
            echo [OK] Frontend is ready.
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
if !FRONTEND_READY! == 0 (
    echo [WARN] Frontend did not respond within 30s, continuing anyway...
)

REM ---- 7. Open browser ----
echo [INFO] Opening browser...
start "" http://localhost:6001
start "" http://localhost:6002/docs

echo.
echo ==============================
echo  All services started!
echo   Frontend: http://localhost:6001
echo   Backend:  http://localhost:6002
echo   API docs: http://localhost:6002/docs
echo.
echo  Logs:
echo   Backend:  %TEMP%\influencer-backend.log
echo   Frontend: %TEMP%\influencer-frontend.log
echo.
echo  Press any key to stop all services...
echo ==============================
echo.
pause >nul

REM ---- 8. Cleanup: kill background services ----
echo [INFO] Stopping services...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":6002 " ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":6001 " ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
echo [OK] Services stopped.
endlocal
