"""One-shot: remove duplicate daily_brief_latest rows, keeping only the newest per date."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import sheets as sh
from src.sync import load_env

TAB = "daily_brief_latest"

def main():
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)
    ws = ss.worksheet(TAB)

    all_values = ws.get_all_values()
    if not all_values:
        print("Sheet is empty")
        return

    header = all_values[0]
    rows = all_values[1:]
    print(f"Found {len(rows)} data rows")

    # Group by date prefix (YYYY-MM-DD), keep the LAST (most recent sync) per date
    best: dict[str, tuple[int, list[str]]] = {}  # date -> (original_index, row)
    for i, row in enumerate(rows):
        date_raw = row[0] if row else ""
        date_key = date_raw[:10]  # "2026-04-15"
        if not date_key:
            continue
        best[date_key] = (i, row)

    keep_count = len(best)
    remove_count = len(rows) - keep_count
    print(f"Unique dates: {keep_count}, duplicates to remove: {remove_count}")

    if remove_count == 0:
        print("No duplicates found.")
        return

    # Rebuild the sheet: header + one row per date, sorted by date
    kept = sorted(best.values(), key=lambda x: x[1][0])  # sort by date (col 0)
    new_data = [header] + [row for _, row in kept]

    # Clear and rewrite
    ws.clear()
    ws.update(f"A1:N{len(new_data)}", new_data, value_input_option="RAW")
    print(f"Rewrote sheet: {len(new_data) - 1} rows (was {len(rows)})")
    for _, row in kept:
        print(f"  kept: {row[0][:20]}  headline: {row[6][:50] if len(row) > 6 else '?'}")


if __name__ == "__main__":
    main()
