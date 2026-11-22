@echo off
rem One-click launcher: creates a virtual environment, installs dependencies, starts the app.
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :fail
start "" http://127.0.0.1:5000
echo Server running at http://127.0.0.1:5000  (press Ctrl+C to stop)
".venv\Scripts\python.exe" app.py
goto :eof
:fail
echo.
echo Setup failed. Make sure Python 3.9+ is installed and on PATH.
pause
