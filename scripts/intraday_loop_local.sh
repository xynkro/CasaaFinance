#!/bin/bash
# Local 10-min intraday alert loop — runs from a launchd agent (see
# scripts/com.caspar.trigger-alerts.plist, StartInterval 600).
#
# Why local: the GitHub Actions */10 cron for trigger-alerts is BEST-EFFORT —
# it delivered 4 runs across the whole 2026-06-09 US session while the user's
# held put credit spreads rode an SPX selloff unpaged. Worse, each GH run fired
# on its own clock relative to the 5-min price grab, so it could evaluate
# minutes-stale prices. This loop fixes both: launchd fires reliably every
# 600s, and it runs the price grab BEFORE the evaluator so trigger_alerts
# always sees a fresh live_prices tab. The GH workflow stays as the
# away-from-Mac backup; the dedup ledgers (trigger_alerts +
# macro_alerts_state) make double-delivery harmless.
set -u
cd "$(dirname "$0")/.." || exit 0
PY="./.venv/bin/python"
LOG=".state/intraday-loop.log"
mkdir -p .state

# Market-hours guard: Mon-Fri, 13:25-21:05 UTC (US cash session 13:30-21:00
# with a 5-min shoulder on each side). Outside the window: silent no-op.
# NOTE: bash [ ] integer comparison is base-10, so "0905" parses as 905 —
# safe with leading zeros (unlike $(( )) which would treat it as octal).
DOW=$(date -u +%u)    # 1=Mon .. 7=Sun
HHMM=$(date -u +%H%M)
[ "$DOW" -ge 6 ] && exit 0
[ "$HHMM" -lt 1325 ] && exit 0
[ "$HHMM" -gt 2105 ] && exit 0

{
  echo "=== $(date '+%F %T') intraday loop ==="
  # Order matters: price grab FIRST, evaluator SECOND — the whole point
  # of the local loop (the GH crons run these on independent schedules,
  # so the evaluator could see prices from before the move).
  "$PY" scripts/tv_price_refresh.py
  echo "tv_price_refresh exit: $?"
  "$PY" scripts/trigger_alerts.py
  echo "trigger_alerts exit: $?"
} >> "$LOG" 2>&1

# Keep the log bounded.
tail -n 800 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
