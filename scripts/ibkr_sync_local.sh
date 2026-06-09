#!/bin/bash
# Local IBKR position sync — runs from a launchd agent every ~30 min.
#
# Pulls positions from the TWS / IB Gateway running on THIS Mac and pushes them
# to the Google Sheet (--sync), which the cloud Firestore mirror then serves to
# the PWA. The cloud crons can't reach your local IBKR, so this is the only thing
# that keeps the *real* book current.
#
# It is a no-op (no log spam) whenever no IBKR API port is listening — i.e. TWS /
# IB Gateway isn't running or you're not logged in. Auto-detects the common
# ports: 7497 (TWS live), 7496 (TWS paper), 4001 (IBG live), 4002 (IBG paper).
set -u
cd "$(dirname "$0")/.." || exit 0
PY="./.venv/bin/python"
LOG=".state/ibkr-sync.log"
mkdir -p .state

# Find a listening IBKR API port (fast 1s probe each). Exit silently if none.
PORT=""
for p in 7497 7496 4001 4002; do
  if "$PY" - "$p" <<'PYEOF' 2>/dev/null
import socket, sys
s = socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PYEOF
  then PORT="$p"; break; fi
done
[ -z "$PORT" ] && exit 0

{
  echo "=== $(date '+%F %T') sync (port $PORT) ==="
  "$PY" src/ibkr_grab.py --sync --merge --port "$PORT"
  echo "exit: $?"
} >> "$LOG" 2>&1

# Keep the log bounded.
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
