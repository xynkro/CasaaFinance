#!/usr/bin/env python3
"""Start CasaaFinance's time-critical GitHub Actions jobs on time, from the GCP VM.

GitHub's cron runs land hours late (the 09:03 ET plan has been starting after
14:00 ET, the 15-minute Firestore copy every 3-7 hours). A workflow_dispatch
starts straight away, so a systemd timer runs this once a minute and it fires
whatever is due on New York time, which keeps the clocks right through DST.

The workflows' own cron lines stay as a backstop. Every job here is safe to run
twice: the ideas DM keeps a ledger, paper orders have deterministic ids, and the
rest overwrite their own rows.

Standard library only. The token lives in ~/.config/casaa-dispatch/token, mode
600: a fine-grained GitHub token limited to this one repo's Actions permission.
Nothing here touches the WaveZero engine or its timers.

Usage:
  casaa_dispatch.py           # fire what's due (what the timer runs)
  casaa_dispatch.py --check   # test the token and print today's schedule
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = "xynkro/CasaaFinance"
ET = ZoneInfo("America/New_York")
TOKEN_PATH = Path.home() / ".config/casaa-dispatch/token"
STATE_PATH = Path.home() / ".local/state/casaa-dispatch/state.json"
CATCH_UP = timedelta(minutes=10)    # a failed or missed start retries this long, then gives up
WEEKDAYS = (0, 1, 2, 3, 4)
TUE_TO_SAT = (1, 2, 3, 4, 5)        # the morning after each session


def every(minutes: int, start: str, end: str) -> list[str]:
    """Clock times from start to end inclusive, `minutes` apart."""
    t = datetime.strptime(start, "%H:%M")
    stop = datetime.strptime(end, "%H:%M")
    out = []
    while t <= stop:
        out.append(t.strftime("%H:%M"))
        t += timedelta(minutes=minutes)
    return out


# (workflow file, days, ET clock times, inputs). Times keep the order the plan
# needs: holdings, then calendars, macro and dealer levels, then the plan.
JOBS = [
    ("ibkr-flex-sync.yml", TUE_TO_SAT, ["05:10"], {}),
    ("finnhub-calendars.yml", WEEKDAYS, ["07:30"], {}),
    ("macro-grab.yml", WEEKDAYS, ["08:15"], {}),
    ("gex-regime.yml", WEEKDAYS, ["08:20"], {}),
    ("daily-ideas-dm.yml", WEEKDAYS, ["08:45", "09:47"], {"dry": "false", "force": "false"}),
    ("build-daily-plan.yml", WEEKDAYS, ["10:03"], {}),
    ("alpaca-paper-execute.yml", WEEKDAYS, ["10:33"], {"execute": "true"}),
    ("unusual-options-scan.yml", WEEKDAYS, ["10:36"], {}),
    ("iv-surface-scan.yml", WEEKDAYS, ["10:38"], {}),
    ("yahoo-grab.yml", WEEKDAYS, every(30, "09:37", "16:07"), {}),
    ("mirror-firestore.yml", WEEKDAYS, every(15, "08:00", "17:00"), {}),
]


def due(now_et: datetime, fired: set[str]) -> list[tuple[str, str, dict]]:
    """(key, workflow, inputs) for each start inside the catch-up window not yet fired."""
    out = []
    for wf, days, clocks, inputs in JOBS:
        if now_et.weekday() not in days:
            continue
        for c in clocks:
            at = now_et.replace(hour=int(c[:2]), minute=int(c[3:]), second=0, microsecond=0)
            key = f"{wf}|{c}"
            if at <= now_et < at + CATCH_UP and key not in fired:
                out.append((key, wf, inputs))
    return out


def load_fired(path: Path, today: str) -> set[str]:
    """Today's fired starts. A missing or unreadable file means none."""
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return set()
    return set(state.get("fired", [])) if state.get("date") == today else set()


def save_fired(path: Path, today: str, fired: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"date": today, "fired": sorted(fired)}))
    tmp.replace(path)


def _call(token: str, method: str, url: str, body: dict | None = None) -> int:
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "casaa-dispatch"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def dispatch(token: str, workflow: str, inputs: dict) -> int:
    return _call(token, "POST", f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches",
                 {"ref": "main", "inputs": inputs})


def read_token(path: Path = TOKEN_PATH) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def tick(now_et: datetime, token: str, send=dispatch, state_path: Path = STATE_PATH) -> int:
    today = now_et.date().isoformat()
    fired = load_fired(state_path, today)
    failed = 0
    for key, wf, inputs in due(now_et, fired):
        code = send(token, wf, inputs)
        print(f"{now_et:%Y-%m-%d %H:%M} ET {wf} -> {code}", flush=True)
        if code == 204:
            fired.add(key)
            save_fired(state_path, today, fired)
        else:                # left unfired, so the next tick retries inside CATCH_UP
            failed += 1
    return failed


def check(token: str, now_et: datetime) -> int:
    code = _call(token, "GET", f"https://api.github.com/repos/{REPO}/actions/workflows/daily-ideas-dm.yml")
    print(f"token: {'OK' if code == 200 else f'FAILED (HTTP {code})'}")
    for wf, days, clocks, _ in JOBS:
        span = clocks[0] if len(clocks) == 1 else f"{clocks[0]}..{clocks[-1]} ({len(clocks)} starts)"
        print(f"  {wf:28s} {span} ET" + ("" if now_et.weekday() in days else "  (not today)"))
    return 0 if code == 200 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    now_et = datetime.now(ET)
    token = read_token()
    if args.check:
        return check(token, now_et)
    if not token:
        print(f"no token at {TOKEN_PATH}: nothing started", flush=True)
        return 0
    tick(now_et, token)
    return 0            # failures are retried and logged; the timer itself stays healthy


if __name__ == "__main__":
    sys.exit(main())
