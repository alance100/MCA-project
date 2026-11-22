#!/usr/bin/env bash
# One-step launcher for Mac/Linux: creates a virtual environment, installs Flask, starts the app.
cd "$(dirname "$0")" || exit 1
[ -d .venv ] || python3 -m venv .venv || { echo "Python 3.9+ is required"; exit 1; }
.venv/bin/python -m pip install -q -r requirements.txt || exit 1
echo "Server running at http://127.0.0.1:5000  (Ctrl+C to stop)"
.venv/bin/python app.py
