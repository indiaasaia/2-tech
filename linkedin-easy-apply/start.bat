@echo off
title LinkedIn Continuous Automation Loop - Meetkumar Raval
cd /d "%~dp0"

echo ==============================================================================
echo   LinkedIn Easy Apply -- 24/7 Continuous Automation Loop & Web Dashboard
echo ==============================================================================
echo.

:: 1. Ensure setup was run
if not exist ".venv\Scripts\python.exe" (
    echo [!] Python virtual environment not found. Running setup.bat first...
    echo.
    call setup.bat
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Setup could not be completed. Please run setup.bat manually.
    pause
    exit /b 1
)

:: 2. Launch Unified Main Loop
echo [*] Launching 24/7 Continuous Sprint Loop...
echo [*] Terminal: Live continuous sprint loop (10-second gap between listings)
echo [*] Web Dashboard: http://localhost:5050
echo [*] Press Ctrl+C in this window at any time to pause or stop.
echo.

.\.venv\Scripts\python.exe -u main.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Continuous runner stopped.
    pause
)
