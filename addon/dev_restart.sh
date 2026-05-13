#!/usr/bin/env bash
# Restart the local Python addon on port 8099. Loads env from addon/.env
# (gitignored; template at addon/.env.example). Logs to /tmp/circadian_local.log.
# Safe to call repeatedly — kills any existing instance first.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
LOG="/tmp/circadian_local.log"
VENV_ACTIVATE="$REPO_ROOT/.venv/bin/activate"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE — copy from addon/.env.example and fill in HA_TOKEN."
  exit 1
fi

# Kill anything on 8099
PID="$(lsof -nP -iTCP:8099 -sTCP:LISTEN -t 2>/dev/null || true)"
if [ -n "$PID" ]; then
  echo "Stopping PID $PID on :8099"
  kill "$PID" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    sleep 0.2
    if ! lsof -nP -iTCP:8099 -sTCP:LISTEN -t >/dev/null 2>&1; then break; fi
  done
fi

# Source venv + env file
# shellcheck disable=SC1090
[ -f "$VENV_ACTIVATE" ] && source "$VENV_ACTIVATE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$SCRIPT_DIR"
nohup python main.py > "$LOG" 2>&1 &
NEW_PID=$!
disown 2>/dev/null || true

# Wait briefly for it to bind
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 0.3
  if lsof -nP -iTCP:8099 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Started PID $NEW_PID on :8099 (log: $LOG)"
    exit 0
  fi
done

echo "Process did not bind :8099 — last log lines:"
tail -20 "$LOG"
exit 1
