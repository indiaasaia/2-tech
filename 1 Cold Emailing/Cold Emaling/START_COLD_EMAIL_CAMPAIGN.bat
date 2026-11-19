@echo off
chcp 65001 >nul
title Cold Email Campaign - Meet Raval
color 0A

echo ============================================================
echo   COLD EMAIL CAMPAIGN - AUTOMATED RUNNER
echo   Target : Germany software companies and startups (Werkstudent/Intern)
echo   Cap    : 20 companies/day, up to 6 emails each (120/day)
echo ============================================================
echo.

REM Project location. Edit this line if you move the folder.
set PROJECT=%~dp0

if not exist "%PROJECT%\phase_3\campaign.py" (
    echo [ERROR] Project folder not found at:
    echo         %PROJECT%
    echo.
    echo Open this .bat file in Notepad and fix the PROJECT path,
    echo then run it again.
    echo.
    pause
    exit /b 1
)

cd /d "%PROJECT%"

REM Use the project venv python so all dependencies are available.
set PYTHON=phase_1\.venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo [INFO] Project : %CD%
echo [INFO] Starting automated campaign loop...
echo [INFO] Live updates appear below. Close this window to stop.
echo.

"%PYTHON%" -m phase_3.campaign --loop

echo.
echo ============================================================
echo   CAMPAIGN RUN FINISHED
echo   (stopped by the daily cap, the agency cap, or the API limit)
echo.
echo   Sent history : phase_3\sent_history.csv
echo   Tracking     : phase_3\data\tracking.csv
echo   Log          : phase_3\data\campaign_log.csv
echo ============================================================
echo.
pause
