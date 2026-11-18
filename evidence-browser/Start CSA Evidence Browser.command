#!/bin/bash
set -euo pipefail

# Finder-launched Terminal sessions may not inherit Homebrew's PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

EVIDENCE_BROWSER_DIR="/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/evidence-browser"
LAUNCHER="$EVIDENCE_BROWSER_DIR/start-dev.sh"

if [[ ! -x "$LAUNCHER" ]]; then
  echo "Evidence Browser launcher is missing or not executable:"
  echo "$LAUNCHER"
  echo
  read -r -p "Press Return to close..." _
  exit 1
fi

cd "$EVIDENCE_BROWSER_DIR"
stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Stopping process(es) on port $port..."
    kill $pids 2>/dev/null || true
  fi
}

# Clear stale Evidence Browser processes before starting a fresh pair.
# 8765 is the configured backend port; 8465 is also cleared for compatibility
# with older local launch configurations.
stop_port 8465
stop_port 8765
stop_port 5173

echo "Starting CSA Evidence Browser..."
echo "Press Control-C to stop it."
echo

exec "$LAUNCHER" "$@"
