#!/usr/bin/env bash
# Start Pramaan on http://localhost:8000 (API + built dashboard).
set -e
cd "$(dirname "$0")/backend"
# Install (or finish a broken install). The marker is only written when pip succeeds.
if [ ! -f .venv/installed-v3.ok ]; then
  echo "Installing Python libraries - this can take a few minutes..."
  [ -x .venv/bin/python ] || { rm -rf .venv; python3 -m venv .venv; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/installed-v3.ok
fi
# Demo clock: keeps expiry checks reproducible for the synthetic data.
export PRAMAAN_TODAY="${PRAMAAN_TODAY:-2026-10-21}"
[ -f storage/pramaan.db ] || .venv/bin/python scripts/seed.py
echo "Open http://localhost:8000  (officer / demo1234)"
exec .venv/bin/python -m uvicorn app.main:app --port 8000
