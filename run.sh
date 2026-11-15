#!/usr/bin/env bash
# BLAQUE ANALYSIS — one-command local start (macOS / Linux)
#
#   ./run.sh                 # install deps if needed, sync once, start server
#   SKIP_SYNC=1 ./run.sh     # start without the initial provider sync
#   PORT=8001 ./run.sh       # use a different port

set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  PYTHON_BIN=".venv/bin/python"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Installing dependencies..."
"$PYTHON_BIN" -m pip install --upgrade pip --quiet
"$PYTHON_BIN" -m pip install -r requirements.txt --quiet

if [ "${SKIP_SYNC:-0}" != "1" ]; then
  echo "Syncing real fixtures from ESPN (first run can take a few minutes)..."
  "$PYTHON_BIN" -m backend.app.cli sync --months-back 15 --months-ahead 1 --workers 1
fi

echo "Starting BLAQUE ANALYSIS at http://localhost:${PORT}"
exec "$PYTHON_BIN" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$PORT"
