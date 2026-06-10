#!/usr/bin/env python3
"""Local IBKR position sync — launchd, every 30 min, TCC-safe python wrapper.

Replaces ibkr_sync_local.sh: launchd's /bin/bash is denied ~/Documents by
macOS TCC ("Operation not permitted"), while the repo's venv python is the
pattern the other com.caspar.* agents have run with. Same behaviour: probe the
common TWS / IB Gateway API ports, silently no-op when none is listening
(IBKR closed / not logged in), otherwise run ibkr_grab --sync --merge against
the live port and log to .state/ibkr-sync.log.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / ".state" / "ibkr-sync.log"
LOG_KEEP_LINES = 500
PORTS = (7497, 7496, 4001, 4002)  # TWS live/paper, IB Gateway live/paper


def listening(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def main() -> int:
    port = next((p for p in PORTS if listening(p)), None)
    if port is None:
        return 0  # IBKR not running — clean no-op, no log spam

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as log:
        log.write(f"=== {datetime.now().strftime('%F %T')} sync (port {port}) ===\n")
        log.flush()
        r = subprocess.run(
            [sys.executable, str(ROOT / "src" / "ibkr_grab.py"),
             "--sync", "--merge", "--port", str(port)],
            cwd=str(ROOT), stdout=log, stderr=log)
        log.write(f"exit: {r.returncode}\n")

    try:
        lines = LOG.read_text().splitlines()
        if len(lines) > LOG_KEEP_LINES:
            LOG.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n")
    except OSError:
        pass
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
