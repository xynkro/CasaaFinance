"""
push_decisions.py — Brain → decision_queue sheet upserter.

Called by the WSR Lite + WSR Monday Opus brain sessions to push their
synthesized Decision Queue (Top 5 + watchlist entries) to the sheet that
the PWA Decisions tab reads.

Replaces the old pattern where decision_queue rows were stale legacy
entries with no brain in the loop.

Input JSON shape (stdin or --json-file):

    {
      "date": "2026-04-29",
      "decisions": [
        {
          "ticker":         "SCHD",
          "account":        "caspar",
          "bucket":         "quality",
          "thesis_1liner":  "CC income unlock at 100 shares — accumulating",
          "conv":           5,
          "entry":          30.40,
          "target":         33.00,
          "status":         "pending"
        },
        ...
      ]
    }

Behaviour:
  - Idempotent upsert by (date, account, ticker) — re-running with same
    date+account+ticker replaces the prior row.
  - Different dates accumulate (history preserved).

Usage:
  cat decisions.json | python scripts/push_decisions.py
  python scripts/push_decisions.py --json-file decisions.json
  python scripts/push_decisions.py --dry --json-file decisions.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("push-decisions")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def push_decisions(payload: dict[str, Any], dry: bool = False) -> dict:
    logger = _setup_logging()

    date = payload.get("date")
    decisions = payload.get("decisions", [])
    if not date:
        return {"ok": False, "error": "missing date"}
    if not isinstance(decisions, list) or not decisions:
        return {"ok": False, "error": "decisions[] must be a non-empty array"}

    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.DecisionRow.TAB_NAME)

    # Build new rows from JSON
    new_rows: list[list[str]] = []
    for d in decisions:
        try:
            row = S.DecisionRow(
                date=date,
                account=d.get("account", "caspar"),
                ticker=d.get("ticker", "").strip().upper(),
                bucket=d.get("bucket", ""),
                thesis_1liner=d.get("thesis_1liner", "").strip(),
                conv=int(d.get("conv", 3)),
                entry=float(d.get("entry", 0)),
                target=float(d.get("target", 0)),
                status=d.get("status", "pending"),
            )
            if not row.ticker:
                continue
            new_rows.append(row.to_row())
            logger.info(f"  + {row.account:7} {row.ticker:6} {row.bucket:12} conv={row.conv} entry=${row.entry:.2f} → ${row.target:.2f}")
        except Exception as e:
            logger.warning(f"  skip malformed entry: {e} ({d})")

    if not new_rows:
        return {"ok": False, "error": "no valid decision rows after parsing"}

    # Upsert: drop existing rows where (date_prefix, account, ticker) matches
    existing = ws.get_all_values()
    keep_rows = [existing[0]] if existing else [list(S.DecisionRow.HEADERS)]
    new_keys = {(date, r[1], r[2]) for r in new_rows}  # (date, account, ticker)
    dropped = 0
    for r in (existing[1:] if existing else []):
        if not r:
            continue
        # Date prefix match (handle audit suffix like "T193908")
        row_date = r[0][:10]
        row_account = r[1] if len(r) > 1 else ""
        row_ticker = r[2] if len(r) > 2 else ""
        if (row_date, row_account, row_ticker) in new_keys:
            dropped += 1
            continue
        keep_rows.append(r)
    keep_rows.extend(new_rows)

    if dry:
        logger.info(f"[DRY] would upsert {len(new_rows)} rows (dropped {dropped} stale)")
        return {"ok": True, "added": len(new_rows), "dropped": dropped, "dry": True}

    ws.clear()
    ws.update("A1", keep_rows, value_input_option="USER_ENTERED")
    logger.info(f"✓ Upserted {len(new_rows)} decision rows (dropped {dropped} stale)")
    return {"ok": True, "added": len(new_rows), "dropped": dropped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json-file", type=Path, help="Path to JSON file. If omitted, reads stdin.")
    ap.add_argument("--dry", action="store_true", help="Print plan, no sheet write")
    args = ap.parse_args()

    if args.json_file:
        text = args.json_file.read_text()
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("ERROR: empty JSON payload", file=sys.stderr)
        return 2
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 2

    result = push_decisions(payload, dry=args.dry)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
