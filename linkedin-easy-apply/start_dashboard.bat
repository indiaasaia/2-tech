@echo off
title LinkedIn Easy Apply Command Center
cd /d "%~dp0"
echo ===================================================================
echo   LinkedIn Easy Apply Autonomous Command Center
echo   - AI Sprint Pipeline (Ollama Fit Rating & Tectonic LaTeX CV)
echo   - Safety Ceiling: 50 Applications/day
echo ===================================================================
echo.
echo Starting dashboard server on http://localhost:5050...
start "" http://localhost:5050
.\.venv\Scripts\python.exe -u dashboard.py
pause
