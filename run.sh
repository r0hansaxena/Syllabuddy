#!/usr/bin/env bash
# One-command launcher: installs everything on first run, then opens the app.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

uv sync --quiet
( sleep 3; open "http://localhost:$PORT" >/dev/null 2>&1 || true ) &
echo "Syllabuddy running at http://localhost:$PORT  (Ctrl+C to stop)"
exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
