@echo off
chcp 65001 >nul
title Send Leftovers - Cold Email Outreach Pipeline
color 0A

echo ============================================================
echo   SEND LEFTOVERS ONLY - OUTREACH DISPATCH ENGINE
echo   Target : Dispatched directly to all unsent discovered contacts
echo   Rules  : No new discovery; human priority; 2/domain cap
echo ============================================================
echo.

set PROJECT=%~dp0
cd /d "%PROJECT%"

set PYTHON=phase_1\.venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo [INFO] Project : %CD%
echo [INFO] Python  : %PYTHON%
echo [INFO] Dispatching emails to leftover contacts in queue...
echo [INFO] Close this terminal window at any time to pause sending.
echo.

"%PYTHON%" phase_3/send_emails.py --mode all

echo.
echo ============================================================
echo   LEFTOVER DISPATCH COMPLETE
echo   All sent emails are permanently saved in state.json and sent_history.csv
echo ============================================================
echo.
pause
