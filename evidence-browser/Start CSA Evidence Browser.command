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
echo "Starting CSA Evidence Browser..."
echo "Press Control-C to stop it."
echo

exec "$LAUNCHER" "$@"
