@echo off
cd /d "%~dp0"
echo ========================================================
echo   Starting LinkedIn Easy Apply Bot (Germany Edition)
echo ========================================================
echo.
.\.venv\Scripts\python.exe apply_bot.py
pause
