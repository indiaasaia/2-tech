@echo off
title LinkedIn Easy Apply - Visible Live Runner
cd /d "%~dp0"
echo ===================================================================
echo   LinkedIn Easy Apply Bot (Visible Desktop Mode)
echo   Target: Germany / DACH - Candidate: Meetkumar Raval
echo ===================================================================
echo.
echo Launching visible Chrome browser on your desktop...
.\.venv\Scripts\python.exe -u apply_bot.py %*
echo.
echo Batch complete. Press any key to exit this window.
pause >nul
