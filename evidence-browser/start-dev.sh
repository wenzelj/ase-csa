#!/usr/bin/env bash
# Start the evidence-browser backend (FastAPI, :8765) and frontend (Vite dev server).
# Usage: ./start-dev.sh [--project iamps] [--port 8765] [any other backend.server args]
# Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

command -v uv  >/dev/null || { echo "uv not found (brew install uv)"; exit 1; }
command -v npm >/dev/null || { echo "npm not found (brew install node)"; exit 1; }

# Install deps on first run
[ -d .venv ] || uv sync
[ -d frontend/node_modules ] || (cd frontend && npm install)

pids=()
cleanup() {
  echo; echo "Stopping..."
  for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting backend on http://127.0.0.1:8765 ..."
uv run python -m backend.server --no-open "$@" &
pids+=($!)

echo "Starting frontend (Vite)..."
(cd frontend && npm run dev) &
pids+=($!)

# Exit when either process dies (bash 3.2 compatible)
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 1; done
