@echo off
rem Starts SpotifySplitter and opens it in the browser. Close this window to stop it.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time...
    py -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"
echo SpotifySplitter is running at http://127.0.0.1:5000 - close this window to stop it.
".venv\Scripts\python.exe" app.py
pause
