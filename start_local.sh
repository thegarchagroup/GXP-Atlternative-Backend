#!/usr/bin/env bash
# One-command local start (Linux/macOS): creates .venv, installs deps, creates .env, runs the API.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  $PY -m venv .venv
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
python scripts/setup_local_env.py
echo ""
echo "API:  http://localhost:1802      Docs: http://localhost:1802/docs"
echo "Press Ctrl+C to stop."
python main.py
