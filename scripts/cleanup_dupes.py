"""
One-shot cleanup: de-duplicate rows per tab and drop junk rows (zero net_liq, etc.).
Keeps only the best row per YYYY-MM-DD date prefix.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import sheets as sh
from src.sync import load_env


def dedup_tab(ss, tab_name: str, value_col: int | None = None):
    """De-duplicate a tab. If value_col is set, prefer rows where that column is non-zero."""
    try:
        ws = ss.worksheet(tab_name)
    except Exception:
        print(f"  {tab_name}: not found, skipping")
        return

    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        print(f"  {tab_name}: empty or header-only")
        return

    header = all_values[0]
    rows = all_values[1:]
    print(f"  {tab_name}: {len(rows)} rows")

    # Group by date prefix (YYYY-MM-DD), keep best row per date
    best: dict[str, list[str]] = {}
    for row in rows:
        date_raw = row[0] if row else ""
        date_key = date_raw[:10]
        if not date_key:
            continue
        existing = best.get(date_key)
        if existing is None:
            best[date_key] = row
        elif value_col is not None:
            # Prefer the row with a non-zero/non-empty value column
            new_val = _nonzero(row, value_col)
            old_val = _nonzero(existing, value_col)
            if new_val and not old_val:
                best[date_key] = row
            elif not new_val and old_val:
                pass  # keep existing
            else:
                best[date_key] = row  # both non-zero or both zero: last wins
        else:
            best[date_key] = row  # last wins

    keep_count = len(best)
    remove_count = len(rows) - keep_count
    if remove_count == 0:
        print(f"    no duplicates")
        return

    kept = sorted(best.items(), key=lambda x: x[0])
    new_data = [header] + [row for _, row in kept]
    ncols = len(header)
    col_letter = chr(ord("A") + ncols - 1) if ncols <= 26 else "Z"
    ws.clear()
    ws.update(f"A1:{col_letter}{len(new_data)}", new_data, value_input_option="RAW")
    print(f"    {len(rows)} → {keep_count} rows (removed {remove_count})")


def _nonzero(row: list[str], col: int) -> bool:
    try:
        v = float(row[col])
        return v != 0
    except (IndexError, ValueError):
        return False


def main():
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    print("Cleaning tabs...")
    # Snapshot tabs: prefer rows where net_liq (col 1) is non-zero
    dedup_tab(ss, "snapshot_caspar", value_col=1)
    dedup_tab(ss, "snapshot_sarah", value_col=1)
    # Daily briefs, macro, positions, archive: last-per-date wins
    dedup_tab(ss, "daily_brief_latest")
    dedup_tab(ss, "macro")
    dedup_tab(ss, "positions_caspar")
    dedup_tab(ss, "positions_sarah")
    dedup_tab(ss, "wsr_archive")
    dedup_tab(ss, "decision_queue")
    dedup_tab(ss, "options")
    print("\nDone.")


if __name__ == "__main__":
    main()
