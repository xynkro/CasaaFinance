#!/usr/bin/env bash
# Install the CasaaFinance job starter on the GCP VM, from the Mac. Separate from
# the WaveZero units: it installs one script and one timer and restarts nothing
# else. The GitHub token is added by hand; see docs/runbooks/vm-job-starter.md.
set -euo pipefail
HOST="${1:-wavezero.us-east1-b.wavezero-paper-1006}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ssh "$HOST" 'mkdir -p ~/casaa-dispatch'
scp -q "$HERE/casaa_dispatch.py" "$HOST:casaa-dispatch/casaa_dispatch.py"
scp -q "$HERE/casaa-dispatch.service" "$HERE/casaa-dispatch.timer" "$HOST:/tmp/"
ssh "$HOST" 'sudo install -m 644 /tmp/casaa-dispatch.service /tmp/casaa-dispatch.timer /etc/systemd/system/ \
  && rm -f /tmp/casaa-dispatch.service /tmp/casaa-dispatch.timer \
  && sudo systemctl daemon-reload && sudo systemctl enable --now casaa-dispatch.timer \
  && systemctl list-timers casaa-dispatch.timer --no-pager | head -3'
