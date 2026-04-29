"""
push_recommendations.py — Brain → option_recommendations sheet upserter.

Called by the WSR Lite + WSR Monday Opus brain sessions to push their
synthesized "Actionable Entries" + options book judgement to the sheet
that the PWA Strategy Notes card reads.

Replaces the old pattern where strategy notes were just rule-filter math
from market_scan.py with no real "why" thesis.

Input JSON shape (stdin or --json-file):

    {
      "date": "2026-04-29",
      "source": "wsr_full" | "wsr_lite" | "manual",
      "recommendations": [
        {
          "ticker":            "MDT",
          "account":           "sarah",
          "strategy":          "BUY_DIP",     // or "CSP", "CC", "PMCC", "LONG_CALL", "LONG_PUT"
          "right":             "",            // "" for share entries; "P"/"C" for options
          "strike":            84.00,         // 0 for share entries
          "expiry":            "",            // "20260620" for options
          "premium_per_share": 0.0,           // 0 for share entries
          "delta":             0.0,
          "annual_yield_pct":  0.0,
          "breakeven":         84.00,
          "cash_required":     8400,          // 100 * strike for CSP
          "iv_rank":           0,
          "thesis_confidence": 0.70,
          "thesis":            "Wide-moat medical, dividend aristocrat, at SMA50 support. Entry $84 → target $96 (15% upside, 8% to stop). Catalysts: Q4 earnings late May, Hugo FDA approvals.",
          "status":            "proposed"
        },
        ...
      ]
    }

Behaviour:
  - Upserts by (date_prefix, source, ticker, strategy, strike) so brain
    re-runs on the same day update rather than duplicate.
  - Different dates accumulate (history preserved).
  - DOES NOT overwrite rows from other sources (e.g. market_scan rows
    survive — only same-source same-day re-runs are deduped).

Usage:
  cat recs.json | python scripts/push_recommendations.py
  python scripts/push_recommendations.py --json-file recs.json --dry
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
    logger = logging.getLogger("push-recs")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def push_recommendations(payload: dict[str, Any], dry: bool = False) -> dict:
    logger = _setup_logging()

    date = payload.get("date")
    source = payload.get("source", "wsr_full")
    recs = payload.get("recommendations", [])
    if not date:
        return {"ok": False, "error": "missing date"}
    if not isinstance(recs, list) or not recs:
        return {"ok": False, "error": "recommendations[] must be a non-empty array"}

    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.OptionRecommendationRow.TAB_NAME, S.OptionRecommendationRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.OptionRecommendationRow.TAB_NAME)

    # Build new rows
    new_rows: list[list[str]] = []
    new_keys: set[tuple] = set()
    for r in recs:
        try:
            row = S.OptionRecommendationRow(
                date=date,
                source=source,
                account=r.get("account", "caspar"),
                ticker=r.get("ticker", "").strip().upper(),
                strategy=r.get("strategy", "").strip().upper(),
                right=(r.get("right", "") or "").strip().upper(),
                strike=float(r.get("strike", 0) or 0),
                expiry=r.get("expiry", "").strip(),
                premium_per_share=float(r.get("premium_per_share", 0) or 0),
                delta=float(r.get("delta", 0) or 0),
                annual_yield_pct=float(r.get("annual_yield_pct", 0) or 0),
                breakeven=float(r.get("breakeven", 0) or 0),
                cash_required=float(r.get("cash_required", 0) or 0),
                iv_rank=float(r.get("iv_rank", 0) or 0),
                thesis_confidence=float(r.get("thesis_confidence", 0.7) or 0.7),
                thesis=(r.get("thesis", "") or "").strip(),
                status=(r.get("status", "proposed") or "proposed").strip(),
            )
            if not row.ticker or not row.thesis:
                continue
            new_rows.append(row.to_row())
            key = (date, source, row.ticker, row.strategy, f"{row.strike:.2f}")
            new_keys.add(key)
            logger.info(f"  + {row.account:7} {row.ticker:6} {row.strategy:9} {row.thesis[:60]}...")
        except Exception as e:
            logger.warning(f"  skip malformed rec: {e}")

    if not new_rows:
        return {"ok": False, "error": "no valid recommendation rows after parsing"}

    # Upsert by (date_prefix, source, ticker, strategy, strike)
    existing = ws.get_all_values()
    keep_rows = [existing[0]] if existing else [list(S.OptionRecommendationRow.HEADERS)]
    dropped = 0
    for er in (existing[1:] if existing else []):
        if not er:
            continue
        # Schema: date(0), source(1), account(2), ticker(3), strategy(4), right(5), strike(6)...
        row_date = er[0][:10]
        row_src = er[1] if len(er) > 1 else ""
        row_tick = er[3] if len(er) > 3 else ""
        row_strat = er[4] if len(er) > 4 else ""
        try:
            row_strike = f"{float(er[6]):.2f}" if len(er) > 6 else ""
        except (ValueError, TypeError):
            row_strike = ""
        key = (row_date, row_src, row_tick, row_strat, row_strike)
        if key in new_keys:
            dropped += 1
            continue
        keep_rows.append(er)
    keep_rows.extend(new_rows)

    if dry:
        logger.info(f"[DRY] would upsert {len(new_rows)} rows (dropped {dropped} stale; source={source})")
        return {"ok": True, "added": len(new_rows), "dropped": dropped, "dry": True}

    ws.clear()
    ws.update("A1", keep_rows, value_input_option="USER_ENTERED")
    logger.info(f"✓ Upserted {len(new_rows)} recommendation rows (dropped {dropped} stale; source={source})")
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

    result = push_recommendations(payload, dry=args.dry)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
