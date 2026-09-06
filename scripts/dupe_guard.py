#!/usr/bin/env python3
"""
Sheet invariant guard — catch the SILENT data regressions.

Two checks, both born from bugs that ran for days with no error, no failing
test, and plausible-looking output:

  1. DUPLICATE ROWS — each one-per-day tab must carry exactly ONE write-time per
     calendar day. Violated first by the SGT/UTC prefix bug, then again by
     daily_tracker.py appending instead of upserting (found 2026-09-06 after
     ~3 copies/day accumulated on sarah + options).
  2. UOA QUALITY LAYER POPULATED — the scanner computes aggressor/structure/
     bias/quality, but on 2026-09-06 all 240 alerts written since 08-26 held
     the dataclass DEFAULTS (aggressor=UNKNOWN, quality=0) because the values
     were dropped crossing UoaAlert -> UoaAlertRow. Nothing raised. This check
     asserts the layer is actually producing values.

Exit 0 = clean, 1 = a check failed (so the workflow step goes red + DMs).

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

# The UOA quality layer went live 2026-09-06 (commit 3f6585a). Alerts written
# before that legitimately carry defaults, so they are excluded from the check.
UOA_QUALITY_LIVE_FROM = "2026-09-06"
UOA_MIN_SAMPLE = 5   # below this, too few alerts to judge — skip, don't fail


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


def check_uoa_quality(alerts: list[dict], today: str,
                      live_from: str = UOA_QUALITY_LIVE_FROM,
                      lookback_days: int = 3,
                      min_sample: int = UOA_MIN_SAMPLE) -> str | None:
    """None = healthy. A string = the problem, when the layer writes only defaults.

    Looks at recent alerts on/after `live_from`. If there is a real sample and
    EVERY one still carries aggressor=UNKNOWN and quality=0, the quality layer
    is not reaching the sheet — which is precisely how the bridge bug hid.
    Too few alerts is NOT a failure (weekend, thin scan): it returns None.
    """
    from datetime import date, timedelta
    try:
        y, m, d = (int(x) for x in today[:10].split("-"))
        floor = (date(y, m, d) - timedelta(days=lookback_days)).isoformat()
    except (ValueError, TypeError):
        return None                      # unparseable clock: fail open
    floor = max(floor, live_from)
    recent = [a for a in alerts if (a.get("date") or "")[:10] >= floor]
    if len(recent) < min_sample:
        return None                      # not enough to judge
    def _q(a):
        try:
            return int(str(a.get("quality") or "0").strip() or 0)
        except ValueError:
            return 0
    graded = [a for a in recent if _q(a) > 0]
    readable = [a for a in recent if (a.get("aggressor") or "UNKNOWN") != "UNKNOWN"]
    if not graded and not readable:
        return (f"uoa_alerts: {len(recent)} alert(s) since {floor} but ALL carry "
                f"default aggressor=UNKNOWN / quality=0 — the quality layer is not "
                f"reaching the sheet (check the UoaAlert -> UoaAlertRow bridge in "
                f"scripts/unusual_options_scan.py)")
    return None


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

    # ── Check 2: is the UOA quality layer actually producing values? ──
    try:
        v = ss.worksheet("uoa_alerts").get_all_values()
        hdr = v[0] if v else []
        alerts = [{hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))}
                  for r in v[1:] if any(r)]
        from datetime import date as _d
        uoa_problem = check_uoa_quality(alerts, _d.today().isoformat())
        if uoa_problem:
            problems.append(uoa_problem)
            print(f"  {'uoa_alerts':20} ❌ quality layer writing defaults only")
        else:
            print(f"  {'uoa_alerts':20} ✅ quality layer populated (or too few to judge)")
    except Exception as e:
        print(f"  {'uoa_alerts':20} SKIP ({type(e).__name__})")

    if not problems:
        print("\nClean — dedup holding and the UOA quality layer is populated.")
        return 0

    msg = ("🚨 SHEET INVARIANT FAILURE:\n"
           + "\n".join(f"• {p}" for p in problems)
           + "\n\nDuplicates → check every writer upserts via "
             "src/sheets.py:replace_today_rows (prefix must come from the BATCH, "
             "never the wall clock). UOA defaults → check the UoaAlert -> "
             "UoaAlertRow bridge in scripts/unusual_options_scan.py.")
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
