@echo off
REM One-command local start (Windows): creates .venv, installs deps, creates .env, runs the API.
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
python scripts\setup_local_env.py
echo.
echo API:  http://localhost:1802      Docs: http://localhost:1802/docs
echo Press Ctrl+C to stop.
python main.py
