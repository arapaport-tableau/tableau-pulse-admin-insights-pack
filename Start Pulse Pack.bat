@echo off
REM Double-click this on Windows to start the Pulse Admin Insights Pack app.
REM The first run sets things up (a minute or two). Every run after that is instant.
cd /d "%~dp0"

if not exist ".venv" (
  echo First-time setup: creating a private workspace and downloading two small helpers...
  echo ^(This happens once and takes a minute or two.^)
  echo.
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo Python 3 was not found. Install it free from https://www.python.org/downloads/
    echo During install, check the box "Add Python to PATH", then double-click this file again.
    echo.
    pause
    exit /b 1
  )
  .venv\Scripts\pip install -q -r requirements.txt
  echo Setup done.
  echo.
)

echo Starting the app. Your browser will open in a moment.
echo Leave this window open while you use the app. Close it when you're finished.
echo.
.venv\Scripts\python app.py
pause
