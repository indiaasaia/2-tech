@echo off
title LinkedIn Easy Apply - Automated Setup Wizard
cd /d "%~dp0"

echo ==============================================================================
echo   LinkedIn Easy Apply Bot -- First-Time Automated Setup Wizard
echo ==============================================================================
echo.

:: 1. Check Python
set "PY_CMD="
python --version >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
    py -3 --version >nul 2>&1 && set "PY_CMD=py -3"
)
if not defined PY_CMD (
    py --version >nul 2>&1 && set "PY_CMD=py"
)
if not defined PY_CMD (
    echo [ERROR] Python was not found in your system PATH!
    echo Please install Python 3.10-3.13 from python.org and CHECK "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo [+] Python installation detected:
%PY_CMD% --version
echo.

:: 2. Setup Virtual Environment
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating isolated Python virtual environment (.venv)...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
)

:: 3. Install Requirements
echo [*] Installing/updating Python dependencies...
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [!] Retrying package installation...
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo [+] All Python packages are installed and ready.
echo.

:: 4. Launch Interactive Setup Wizard
echo [*] Launching Interactive Setup & Diagnostic Wizard...
echo.
.\.venv\Scripts\python.exe setup_wizard.py

echo.
pause
