@echo off
chcp 65001 >nul
title Outreach Control Center Dashboard - Meet Raval
color 0B

echo ============================================================
echo   OUTREACH CONTROL CENTER - REAL-TIME LIVE DASHBOARD
echo   Realtime pipeline stepper, current step results and history
echo ============================================================
echo.

set PROJECT=%~dp0
cd /d "%PROJECT%"

REM Auto-detect Python environment with Streamlit installed
set PYTHON=
if exist "phase_1\.venv\Scripts\python.exe" (
    "phase_1\.venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
    if not errorlevel 1 (
        set PYTHON=phase_1\.venv\Scripts\python.exe
    )
)
if "%PYTHON%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import streamlit" >nul 2>nul
        if not errorlevel 1 (
            set PYTHON=python
        )
    )
)
if "%PYTHON%"=="" set PYTHON=python

echo [INFO] Project : %CD%
echo [INFO] Python  : %PYTHON%
echo [INFO] Starting Streamlit Live Dashboard on http://localhost:8501 ...
echo [INFO] Press Ctrl+C in this terminal window to stop the dashboard.
echo.

"%PYTHON%" -m streamlit run streamlit_app/app.py

pause
