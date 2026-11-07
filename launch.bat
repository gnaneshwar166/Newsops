@echo off
setlocal enabledelayedexpansion
title NewsOps Launcher

echo ===================================================
echo             NewsOps Intelligence Engine
echo ===================================================
echo.
echo Choose launch mode:
echo   [1] Docker Compose (Runs Mongo + Backend + Web in Docker)
echo   [2] Local Dev Mode (Python Backend + Next.js Web locally)
echo   [3] Run Tests (pytest backend tests)
echo   [4] Exit
echo.
set /p choice="Enter choice [1-4] (default is 2): "

if "%choice%"=="" set choice=2

if "%choice%"=="1" (
    echo.
    echo [*] Starting Docker Compose...
    docker compose up --build
    goto end
)

if "%choice%"=="2" (
    echo.
    echo [*] Checking if NewsOps Backend is running on http://localhost:8000...
    curl -s http://localhost:8000/api/v1/healthz >nul 2>&1
    if errorlevel 1 (
        echo [*] Starting NewsOps Backend...
        start "NewsOps Backend" cmd /k "python run_backend.py"
        timeout /t 3 /nobreak >nul
    ) else (
        echo [OK] Backend is already running on http://localhost:8000
    )

    echo [*] Checking if NewsOps Web is running on http://localhost:3000...
    curl -s http://localhost:3000/ >nul 2>&1
    if errorlevel 1 (
        echo [*] Starting NewsOps Web Frontend (Next.js)...
        start "NewsOps Web" cmd /k "cd web && npm run dev"
        echo [*] Waiting for Next.js dev server to initialize...
        timeout /t 6 /nobreak >nul
    ) else (
        echo [OK] Web Frontend is already running on http://localhost:3000
    )

    echo [*] Opening browser to http://localhost:3000...
    start http://localhost:3000

    echo.
    echo ===================================================
    echo NewsOps is running!
    echo   - Web UI: http://localhost:3000
    echo   - Backend API Docs: http://localhost:8000/docs
    echo ===================================================
    echo.
    echo Keep the opened command windows running. Close them to stop NewsOps.
    goto end
)

if "%choice%"=="3" (
    echo.
    echo [*] Running Pytest suite...
    python -m pytest tests -v
    echo.
    pause
    goto end
)

:end
