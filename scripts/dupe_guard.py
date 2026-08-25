#!/usr/bin/env python3
"""
Duplicate-row guard — catch a regression of the SGT/UTC dedup bug.

`replace_today_rows` once derived its "today" prefix from the wall clock while
rows are stamped SGT. On a UTC runner, throughout US market hours (21:30-04:00
SGT) the prefix never matched, dedup never fired, and every grab appended.
positions_sarah reached 10x duplicate rows per ticker per day and NOTHING
surfaced it — no error, no failing test, just silently wrong numbers for months.

That is the failure mode worth guarding: silent, slow, and invisible in the UI.
This checks the invariant directly — each tab should carry exactly ONE write-time
per calendar day — and fails loudly if that stops being true.

Exit 0 = clean, 1 = duplicates found (so a workflow step goes red).

USAGE
  python scripts/dupe_guard.py               # check, print
  python scripts/dupe_guard.py --telegram    # DM on failure only
  python scripts/dupe_guard.py --days 3      # only inspect the last N days
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sheets as sh  # noqa: E402
from src.sync import load_env  # noqa: E402

WATCHED = ["positions_caspar", "positions_sarah", "snapshot_caspar",
           "snapshot_sarah", "options"]


def find_duplicate_days(rows: list[list], last_n_days: int | None = None
                        ) -> list[tuple[str, int]]:
    """(day, write_time_count) for days carrying more than one write-time."""
    per_day: dict[str, set] = defaultdict(set)
    for r in rows:
        if not r:
            continue
        stamp = str(r[0] or "").strip()
        if len(stamp) < 10:
            continue
        per_day[stamp[:10]].add(stamp)
    days = sorted(per_day)
    if last_n_days:
        days = days[-last_n_days:]
    return [(d, len(per_day[d])) for d in days if len(per_day[d]) > 1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--telegram", action="store_true", help="DM on failure only")
    ap.add_argument("--days", type=int, default=None,
                    help="Only inspect the most recent N days")
    args = ap.parse_args()

    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    problems: list[str] = []
    for tab in WATCHED:
        try:
            values = ss.worksheet(tab).get_all_values()
        except Exception as e:
            print(f"  {tab:20} SKIP ({type(e).__name__})")
            continue
        dupes = find_duplicate_days(values[1:], args.days)
        if dupes:
            worst = max(dupes, key=lambda x: x[1])
            problems.append(f"{tab}: {len(dupes)} day(s) with repeats, worst "
                            f"{worst[0]} x{worst[1]}")
            print(f"  {tab:20} ❌ {len(dupes)} day(s) duplicated (worst {worst[0]} x{worst[1]})")
        else:
            print(f"  {tab:20} ✅ one write-time per day")

    if not problems:
        print("\nClean — the SGT/UTC dedup fix is holding.")
        return 0

    msg = ("🚨 DUPLICATE ROWS DETECTED — the SGT/UTC dedup fix has regressed:\n"
           + "\n".join(f"• {p}" for p in problems)
           + "\n\nCheck src/sheets.py:replace_today_rows (the prefix must come "
             "from the batch being written, never the wall clock).")
    print("\n" + msg)
    if args.telegram:
        try:
            from src import telegram as tg
            tg.send(msg[:3900], chat_id=tg.PERSONAL_CHAT_ID)
            print("[telegram] alert sent to DM")
        except Exception as e:
            print(f"[telegram] send failed: {e}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
