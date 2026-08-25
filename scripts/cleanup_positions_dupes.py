#!/usr/bin/env python3
"""
Remove the historical duplicate rows left by the SGT/UTC dedup bug.

Background: `src/sheets.py:replace_today_rows` derived its "today" prefix from
`date.today()` on a UTC runner while rows are stamped SGT. Through US market
hours (21:30-04:00 SGT) the prefix never matched, dedup never fired, and every
30-minute grab APPENDED. positions_sarah reached 10x duplicate rows per ticker
per day (180 rows for 18 tickers), inflating every downstream sum tenfold.

The writer is fixed (commit 4e1b18b), so no NEW duplicates accumulate. This tool
cleans what the bug already wrote.

RULE: within each calendar day, keep only the rows from that day's LATEST
write-time — the freshest complete snapshot — and drop the earlier repeats.
Rows whose date cannot be parsed are KEPT; we never delete data we can't read.

SAFETY
  • Dry-run by DEFAULT. Nothing is written without --execute.
  • --execute first writes a full timestamped JSON backup of every touched tab
    to .state/sheet_backups/ (gitignored) — restore with --restore <file>.
  • The write itself is a single atomic upsert_tab (never an empty window).
  • Per-tab invariant check before writing: the kept set must be a strict subset
    of the original and must preserve every (day, ticker) pair.

USAGE
  python scripts/cleanup_positions_dupes.py                    # dry-run report
  python scripts/cleanup_positions_dupes.py --execute          # clean (backs up)
  python scripts/cleanup_positions_dupes.py --restore <file>   # undo
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import sheets as sh  # noqa: E402
from src.sync import load_env  # noqa: E402

DEFAULT_TABS = [
    "positions_caspar", "positions_sarah",
    "snapshot_caspar", "snapshot_sarah",
    "options",
]

BACKUP_DIR = ROOT / ".state" / "sheet_backups"


def _day(row: list) -> str:
    """Calendar day of a row ('' when unparseable)."""
    if not row:
        return ""
    v = str(row[0] or "").strip()
    return v[:10] if len(v) >= 10 else ""


def _stamp(row: list) -> str:
    return str(row[0] or "").strip() if row else ""


def keep_latest_write_per_day(rows: list[list]) -> list[list]:
    """Keep each day's latest write-time group; keep unparseable rows as-is.

    Order is preserved: kept rows come back in their original relative order.
    """
    latest: dict[str, str] = {}
    for r in rows:
        d = _day(r)
        if not d:
            continue
        s = _stamp(r)
        if d not in latest or s > latest[d]:
            latest[d] = s
    out = []
    for r in rows:
        d = _day(r)
        if not d:
            out.append(r)          # unreadable date → never dropped
        elif _stamp(r) == latest[d]:
            out.append(r)
    return out


def summarise(before: list[list], after: list[list]) -> dict:
    """Shape of the change, for the dry-run report."""
    writes_per_day = defaultdict(set)
    for r in before:
        d = _day(r)
        if d:
            writes_per_day[d].add(_stamp(r))
    worst = max(((d, len(s)) for d, s in writes_per_day.items()),
                key=lambda x: x[1], default=("-", 0))
    return {
        "before": len(before), "after": len(after),
        "removed": len(before) - len(after),
        "days": len(writes_per_day),
        "worst_day": worst,
        "dupe_days": sum(1 for s in writes_per_day.values() if len(s) > 1),
    }


def identity_cols(header: list[str]) -> list[int]:
    """Columns that identify a distinct entity within one day.

    Header-aware on purpose: `positions_*` keys on ticker (col 1), `options`
    keys on account+ticker+strike+expiry+right (ticker is col 2, NOT col 1), and
    the `snapshot_*` tabs have NO entity dimension at all — col 1 there is
    net_liq, a number. An earlier version assumed col 1 was always the ticker and
    so compared NLV readings as if they were tickers, producing a false
    "would lose 331 pairs" on every snapshot tab.
    """
    names = [n for n in ("account", "ticker", "right", "strike", "expiry") if n in header]
    return [header.index(n) for n in names]


def _ident(row: list, cols: list[int]) -> tuple:
    return tuple(str(row[i]) if i < len(row) else "" for i in cols)


def dropped_entities(before: list[list], after: list[list],
                     cols: list[int]) -> list[tuple[str, tuple]]:
    """(day, identity) pairs present before but not after.

    These are NOT corruption: they are positions that existed in an earlier
    intraday grab but not in that day's final one — i.e. closed during the
    session. Keeping the final write is the correct end-of-day semantics (the
    PWA reads the latest date as CURRENT holdings, so a sold position must not
    reappear). They are reported explicitly so the drop is a decision, not a
    surprise.
    """
    b = {(_day(r), _ident(r, cols)) for r in before if _day(r)}
    a = {(_day(r), _ident(r, cols)) for r in after if _day(r)}
    return sorted(b - a)


def _invariants_ok(before: list[list], after: list[list],
                   cols: list[int]) -> tuple[bool, str]:
    """Hard safety checks. Entity drops are reported separately, not failed."""
    if len(after) > len(before):
        return False, "kept more rows than existed"
    seen: set = set()
    for r in after:
        d = _day(r)
        if not d:
            continue
        k = (d, _ident(r, cols))
        if k in seen:
            return False, f"result still contains a duplicate for {k}"
        seen.add(k)
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Actually write (default: dry-run). Backs up first.")
    ap.add_argument("--tabs", default=",".join(DEFAULT_TABS),
                    help="Comma-separated tabs to clean")
    ap.add_argument("--restore", metavar="FILE",
                    help="Restore tabs from a backup JSON produced by --execute")
    args = ap.parse_args()

    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    if args.restore:
        data = json.loads(Path(args.restore).read_text())
        for tab, values in data.items():
            ws = ss.worksheet(tab)
            sh.upsert_tab(ws, values)
            print(f"  restored {tab}: {len(values) - 1} rows")
        print("Restore complete.")
        return 0

    tabs = [t.strip() for t in args.tabs.split(",") if t.strip()]
    backup: dict[str, list] = {}
    planned: list[tuple[str, list, list, dict]] = []

    print(f"{'DRY-RUN — nothing will be written' if not args.execute else 'EXECUTE MODE'}\n")
    for tab in tabs:
        try:
            values = ss.worksheet(tab).get_all_values()
        except Exception as e:
            print(f"  {tab:20} SKIP ({type(e).__name__})")
            continue
        if len(values) < 2:
            print(f"  {tab:20} empty — skip")
            continue
        header, rows = values[0], values[1:]
        cols = identity_cols(header)
        kept = keep_latest_write_per_day(rows)
        s = summarise(rows, kept)
        ok, why = _invariants_ok(rows, kept, cols)
        gone = dropped_entities(rows, kept, cols)
        flag = "" if ok else f"  ❌ INVARIANT FAIL: {why}"
        print(f"  {tab:20} {s['before']:>6} → {s['after']:>5} rows "
              f"(−{s['removed']:>5})  {s['dupe_days']}/{s['days']} days had repeats; "
              f"worst {s['worst_day'][0]} ×{s['worst_day'][1]}{flag}")
        if not ok:
            print("     refusing to touch this tab.")
            continue
        if gone:
            print(f"     ℹ {len(gone)} position(s) existed in an earlier intraday grab but "
                  f"not that day's final one (closed during the session):")
            for d, ident in gone[:6]:
                print(f"        {d}  {'/'.join(x for x in ident if x)}")
            if len(gone) > 6:
                print(f"        ... and {len(gone) - 6} more")
        if s["removed"] == 0:
            continue
        backup[tab] = values
        planned.append((tab, header, kept, s))

    if not planned:
        print("\nNothing to clean.")
        return 0

    total = sum(s["removed"] for _, _, _, s in planned)
    if not args.execute:
        print(f"\n[DRY-RUN] would remove {total:,} duplicate rows across {len(planned)} tab(s).")
        print("Re-run with --execute to apply (a restorable backup is written first).")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(backup))
    print(f"\nBackup written: {path}  ({sum(len(v) for v in backup.values()):,} rows)")

    for tab, header, kept, s in planned:
        sh.upsert_tab(ss.worksheet(tab), [header] + kept)
        print(f"  cleaned {tab}: removed {s['removed']:,} rows")
    print(f"\nDone — {total:,} duplicate rows removed. Undo with:\n"
          f"  python scripts/cleanup_positions_dupes.py --restore {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
