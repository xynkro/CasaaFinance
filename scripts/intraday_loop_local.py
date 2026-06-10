#!/usr/bin/env python3
"""Local intraday loop — price grab THEN alert evaluation, every 10 min.

Run by launchd (com.caspar.trigger-alerts) with the repo's .venv python as
ProgramArguments[0]. A bash wrapper version of this was silently killed by
macOS TCC: launchd's /bin/bash gets "Operation not permitted" reading
~/Documents, while the venv python is the pattern this repo's other launchd
agents have run with for months. Keep ALL logic here in python for that reason.

Guard: weekdays, 13:25-21:05 UTC (US session + buffer). Outside → silent no-op.
Order matters: tv_price_refresh BEFORE trigger_alerts, so evaluations never use
the previous grab's prices (the anti-phasing bug found in the 06-09 incident).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / ".state" / "intraday-loop.log"
LOG_KEEP_LINES = 800


def in_window(now: datetime) -> bool:
    if now.weekday() > 4:  # Sat/Sun
        return False
    minutes = now.hour * 60 + now.minute
    return (13 * 60 + 25) <= minutes <= (21 * 60 + 5)


def main() -> int:
    now = datetime.now(timezone.utc)
    if not in_window(now):
        return 0

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as log:
        log.write(f"=== {now.strftime('%Y-%m-%d %H:%M:%S')} UTC cycle ===\n")
        log.flush()
        rc = 0
        for script in ("scripts/tv_price_refresh.py", "scripts/trigger_alerts.py"):
            r = subprocess.run([sys.executable, str(ROOT / script)],
                               cwd=str(ROOT), stdout=log, stderr=log)
            log.write(f"{script} exit: {r.returncode}\n")
            log.flush()
            if r.returncode != 0:
                rc = r.returncode

    # Bound the log.
    try:
        lines = LOG.read_text().splitlines()
        if len(lines) > LOG_KEEP_LINES:
            LOG.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n")
    except OSError:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
