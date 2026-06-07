"""sync_alpaca.py — Pull Alpaca paper positions + account snapshot to Sheets.

Reads open positions + account summary from Alpaca REST v2 and writes
to snapshot_alpaca / positions_alpaca tabs. UPSERT semantics: clears
old rows for today's date, writes fresh.

Usage:
  python scripts/sync_alpaca.py           # sync to sheets
  python scripts/sync_alpaca.py --dry     # print to stdout, no sheet write
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env          # noqa: E402
from src import alpaca as alp          # noqa: E402
from src import sheets as sh           # noqa: E402
from src import schema as S            # noqa: E402


def _sgt_today() -> str:
    sgt = timezone(timedelta(hours=8))
    return datetime.now(sgt).strftime("%Y-%m-%d")


def sync(dry: bool = False) -> dict:
    load_env()

    account = alp.get_account()
    positions = alp.get_positions()
    today = _sgt_today()

    snap = S.AlpacaSnapshotRow(
        date=today,
        net_liq=account.get("portfolio_value", "0"),
        cash=account.get("cash", "0"),
        buying_power=account.get("buying_power", "0"),
        long_value=account.get("long_market_value", "0"),
        short_value=account.get("short_market_value", "0"),
    )

    # Attribution: this paper account is shared with other bots (ZeroDTE 0-DTE
    # SPY + the untagged decision-queue executor). Tag each position by whether
    # FinancePWA's casaa- executor placed it, so the PWA can show its own book
    # cleanly instead of someone else's trades mixed in.
    try:
        owned = alp.financepwa_symbols(alp.get_orders(status="all", limit=500))
    except Exception:
        owned = set()

    pos_rows = []
    for p in positions:
        upl = float(p.get("unrealized_pl", 0))
        cost_basis = float(p.get("cost_basis", 1)) or 1
        upl_pct = (upl / cost_basis) * 100
        sym = p.get("symbol", "")
        pos_rows.append(S.AlpacaPositionRow(
            date=today,
            ticker=sym,
            qty=str(p.get("qty", "0")),
            avg_cost=str(p.get("avg_entry_price", "0")),
            last=str(p.get("current_price", "0")),
            mkt_val=str(p.get("market_value", "0")),
            upl=str(round(upl, 2)),
            upl_pct=str(round(upl_pct, 2)),
            side=p.get("side", "long"),
            origin=("casaa" if (not owned or sym in owned) else "external"),
        ))

    if dry:
        print(json.dumps({
            "snapshot": snap.to_row(audit=False),
            "positions": [r.to_row() for r in pos_rows],
        }, indent=2))
        return {"ok": True, "dry": True, "positions": len(pos_rows)}

    client = sh.authenticate()

    sh.ensure_headers(client, S.AlpacaSnapshotRow.TAB_NAME, S.AlpacaSnapshotRow.HEADERS)
    sh.append_row(client, S.AlpacaSnapshotRow.TAB_NAME, snap.to_row())
    print(f"OK snapshot_alpaca: NLV={snap.net_liq} cash={snap.cash}")

    sh.ensure_headers(client, S.AlpacaPositionRow.TAB_NAME, S.AlpacaPositionRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.AlpacaPositionRow.TAB_NAME)
    existing = ws.get_all_values()
    keep = [existing[0]] if existing else [S.AlpacaPositionRow.HEADERS]
    for r in (existing[1:] if existing else []):
        if r and r[0][:10] != today:
            keep.append(r)
    for pr in pos_rows:
        keep.append(pr.to_row())
    sh.upsert_tab(ws, keep)
    print(f"OK positions_alpaca: {len(pos_rows)} positions")

    return {"ok": True, "positions": len(pos_rows)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    result = sync(dry=args.dry)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
