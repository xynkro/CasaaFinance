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
          "ticker":            "SCHD",
          "account":           "caspar",
          "bucket":            "quality",
          "thesis_1liner":     "CC income unlock at 100 shares — accumulating",
          "conv":              5,
          "entry":             30.40,
          "target":            33.00,
          "status":            "pending",
          // --- optional options-spec fields (default "" / 0 for share entries) ---
          "strategy":          "BUY_DIP",   // or "" / "CSP" / "CC" / "PMCC" / ...
          "right":             "",          // "" / "C" / "P"
          "strike":            0,
          "expiry":            "",          // "YYYYMMDD" for options
          "premium_per_share": 0,
          "delta":             0,
          "annual_yield_pct":  0,
          "breakeven":         0,
          "cash_required":     0,
          "iv_rank":           0,
          "thesis_confidence": 0.70,
          "thesis":            "<long-form brain thesis>",
          "source":            "wsr_full"   // "" / "wsr_full" / "wsr_lite" / "manual"
        },
        ...
      ]
    }

Behaviour:
  - Idempotent upsert by (date, account, ticker, strategy, strike) — same
    compound key as push_recommendations.py. Lets the brain emit BUY_DIP MDT
    AND a hypothetical CSP MDT in the same week without one clobbering the
    other. For legacy share-only rows (strategy="", strike=0) the key
    collapses naturally to (date, account, ticker, "", "0.00").
  - Different dates accumulate (history preserved).
  - Backward-compat: legacy rows in the sheet with only 9 columns are
    pad-read to the new 22-col HEADERS — gspread returns shorter lists
    for short rows, so we defensively index past length.

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
    new_keys: set[tuple] = set()
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
                # Optional options-spec fields — default "" / 0 for share entries.
                strategy=(d.get("strategy", "") or "").strip().upper(),
                right=(d.get("right", "") or "").strip().upper(),
                strike=float(d.get("strike", 0) or 0),
                expiry=(d.get("expiry", "") or "").strip(),
                premium_per_share=float(d.get("premium_per_share", 0) or 0),
                delta=float(d.get("delta", 0) or 0),
                annual_yield_pct=float(d.get("annual_yield_pct", 0) or 0),
                breakeven=float(d.get("breakeven", 0) or 0),
                cash_required=float(d.get("cash_required", 0) or 0),
                iv_rank=float(d.get("iv_rank", 0) or 0),
                thesis_confidence=float(d.get("thesis_confidence", 0) or 0),
                thesis=(d.get("thesis", "") or "").strip(),
                source=(d.get("source", "") or "").strip(),
            )
            if not row.ticker:
                continue
            new_rows.append(row.to_row())
            key = (date, row.account, row.ticker, row.strategy, f"{row.strike:.2f}")
            new_keys.add(key)
            logger.info(
                f"  + {row.account:7} {row.ticker:6} {row.bucket:12} {row.strategy:9} "
                f"conv={row.conv} entry=${row.entry:.2f} → ${row.target:.2f}"
            )
        except Exception as e:
            logger.warning(f"  skip malformed entry: {e} ({d})")

    if not new_rows:
        return {"ok": False, "error": "no valid decision rows after parsing"}

    # Upsert: drop existing rows where (date_prefix, account, ticker, strategy, strike) matches.
    # Legacy 9-col rows have no strategy/strike columns — they pad-read to "" / "0.00",
    # which means a legacy share-only row collapses to the same key as a new BUY_DIP entry
    # ONLY if the new entry also leaves strategy="" — share entries from the new brain
    # carry strategy="BUY_DIP" so they don't collide with legacy share rows.
    existing = ws.get_all_values()
    keep_rows = [existing[0]] if existing else [list(S.DecisionRow.HEADERS)]
    # Schema: date(0), account(1), ticker(2), bucket(3), thesis_1liner(4), conv(5),
    # entry(6), target(7), status(8), strategy(9), right(10), strike(11), ...
    dropped = 0
    for r in (existing[1:] if existing else []):
        if not r:
            continue
        # Date prefix match (handle audit suffix like "T193908")
        row_date = r[0][:10]
        row_account = r[1] if len(r) > 1 else ""
        row_ticker = r[2] if len(r) > 2 else ""
        row_strategy = r[9] if len(r) > 9 else ""
        try:
            row_strike = f"{float(r[11]):.2f}" if len(r) > 11 and r[11] not in ("", None) else "0.00"
        except (ValueError, TypeError):
            row_strike = "0.00"
        if (row_date, row_account, row_ticker, row_strategy, row_strike) in new_keys:
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
