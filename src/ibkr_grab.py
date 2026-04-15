#!/usr/bin/env python3
"""
ibkr_grab.py — Connect to IBKR TWS on localhost, grab both accounts'
portfolio data, and write a PortfolioGrab JSON file.

Usage:
  python src/ibkr_grab.py                    # grab + write JSON
  python src/ibkr_grab.py --sync             # grab + write JSON + sync to Sheet
  python src/ibkr_grab.py --port 7496        # paper trading port

Requires TWS or IB Gateway running with API connections enabled.
TWS: Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients
Port: 7497 (live TWS), 7496 (paper), 4001/4002 (IB Gateway)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import asyncio

# ib_insync needs an event loop at import time on Python 3.12+
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, AccountValue, PortfolioItem


# ---------- config ----------

CASPAR_ACCOUNT = "U6773281"
SARAH_ACCOUNT = "U16000287"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7497
CLIENT_ID = 10  # unique client ID to avoid conflicts with other TWS connections

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "PortfolioGrabs"


def grab_account(ib: IB, account_id: str) -> dict:
    """Pull summary + positions for one account."""
    # Account summary values we care about
    summary_raw = ib.accountSummary(account_id)
    summary_map: dict[str, str] = {}
    for av in summary_raw:
        if isinstance(av, AccountValue) and av.account == account_id:
            summary_map[av.tag] = av.value

    # Portfolio positions
    positions_raw = [p for p in ib.portfolio(account_id)]

    stocks = []
    options = []

    for p in positions_raw:
        c = p.contract
        row = {
            "symbol": c.symbol,
            "sec_type": c.secType,
            "exchange": c.exchange or c.primaryExchange or "",
            "qty": float(p.position),
            "avg_cost": float(p.averageCost),
            "last": float(p.marketPrice),
            "mkt_val": float(p.marketValue),
            "upl": float(p.unrealizedPNL),
        }

        if c.secType == "OPT":
            row["side"] = "short_call" if p.position < 0 else "long_call"
            row["avg_cost_credit"] = abs(float(p.averageCost))
            options.append(row)
        else:
            stocks.append(row)

    # Compute weights
    net_liq = float(summary_map.get("NetLiquidation", 0))
    for s in stocks:
        s["weight_pct"] = round(abs(s["mkt_val"]) / net_liq * 100, 2) if net_liq else 0

    return {
        "account_id": account_id,
        "summary_raw": summary_map,
        "stocks": stocks,
        "options": options,
        "net_liq": net_liq,
    }


def build_grab_json(caspar_data: dict, sarah_data: dict) -> dict:
    """Assemble the PortfolioGrab JSON in the schema the sync layer expects."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    cs = caspar_data["summary_raw"]
    ss = sarah_data["summary_raw"]

    caspar_net_liq = caspar_data["net_liq"]
    sarah_net_liq = sarah_data["net_liq"]

    grab = {
        "grab_date": date_str,
        "grab_timestamp_sgt": now.astimezone().isoformat(),
        "source": "IBKR TWS (localhost direct)",
        "schema_version": "1.1",
        "writer": "ibkr_grab.py",
        "accounts": {
            "caspar": {
                "account_id": CASPAR_ACCOUNT,
                "base_currency": "USD",
                "summary": {
                    "net_liquidation": caspar_net_liq,
                    "buying_power": float(cs.get("BuyingPower", 0)),
                    "total_cash": float(cs.get("TotalCashValue", 0)),
                    "unrealized_pnl": float(cs.get("UnrealizedPnL", 0)),
                    "realized_pnl": float(cs.get("RealizedPnL", 0)),
                    "excess_liquidity": float(cs.get("ExcessLiquidity", 0)),
                    "total_market_value": float(cs.get("GrossPositionValue", cs.get("StockMarketValue", 0))),
                },
                "positions": caspar_data["stocks"],
            },
            "sarah": {
                "account_id": SARAH_ACCOUNT,
                "base_currency": "SGD",
                "summary": {
                    "net_liquidation_sgd": sarah_net_liq,
                    "buying_power_sgd": float(ss.get("BuyingPower", 0)),
                    "total_cash_sgd": float(ss.get("TotalCashValue", 0)),
                    "unrealized_pnl_mixed": float(ss.get("UnrealizedPnL", 0)),
                    "realized_pnl": float(ss.get("RealizedPnL", 0)),
                    "excess_liquidity_sgd": float(ss.get("ExcessLiquidity", 0)),
                    "total_market_value_mixed": float(ss.get("GrossPositionValue", ss.get("StockMarketValue", 0))),
                },
                "positions": sarah_data["stocks"],
                "options": sarah_data["options"],
            },
        },
    }

    return grab


def main():
    import argparse
    p = argparse.ArgumentParser(description="Grab IBKR portfolio via TWS API")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--client-id", type=int, default=CLIENT_ID)
    p.add_argument("--sync", action="store_true", help="Also run sync.py grab after saving JSON")
    p.add_argument("--merge", action="store_true",
                   help="Preserve the other account's data from today's existing grab file "
                        "when only one account is connected")
    args = p.parse_args()

    print(f"Connecting to TWS at {args.host}:{args.port} (client {args.client_id})...")
    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=10)
    except Exception as e:
        print(f"Failed to connect to TWS: {e}", file=sys.stderr)
        print("Make sure TWS is running and API connections are enabled.", file=sys.stderr)
        return 2

    try:
        managed = ib.managedAccounts()
        print(f"Connected. Managed accounts: {managed}")

        caspar_live = CASPAR_ACCOUNT in managed
        sarah_live = SARAH_ACCOUNT in managed

        if not caspar_live:
            print(f"  {CASPAR_ACCOUNT} not connected")
        if not sarah_live:
            print(f"  {SARAH_ACCOUNT} not connected")

        print(f"Grabbing {CASPAR_ACCOUNT}...")
        caspar_data = grab_account(ib, CASPAR_ACCOUNT)
        print(f"  {len(caspar_data['stocks'])} stocks, net liq ${caspar_data['net_liq']:,.2f}")

        print(f"Grabbing {SARAH_ACCOUNT}...")
        sarah_data = grab_account(ib, SARAH_ACCOUNT)
        print(f"  {len(sarah_data['stocks'])} stocks, {len(sarah_data['options'])} options, net liq S${sarah_data['net_liq']:,.2f}")

        grab = build_grab_json(caspar_data, sarah_data)

        # --- Merge: backfill the missing account from today's existing file ---
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        date_str = grab["grab_date"].replace("-", "")
        out_path = OUTPUT_DIR / f"{date_str}_PortfolioGrab.json"

        if args.merge and out_path.exists():
            prev = json.loads(out_path.read_text())
            prev_accounts = prev.get("accounts", {})

            if not caspar_live and prev_accounts.get("caspar", {}).get("positions"):
                print(f"  --merge: backfilling Caspar from previous grab")
                grab["accounts"]["caspar"] = prev_accounts["caspar"]

            if not sarah_live and prev_accounts.get("sarah", {}).get("positions"):
                print(f"  --merge: backfilling Sarah from previous grab")
                grab["accounts"]["sarah"] = prev_accounts["sarah"]

        # Write JSON
        out_path.write_text(json.dumps(grab, indent=2))
        print(f"\nSaved: {out_path}")

        # Optionally sync
        if args.sync:
            print("\nRunning sync.py grab...")
            project_root = Path(__file__).resolve().parent.parent
            result = subprocess.run(
                [sys.executable, "src/sync.py", "grab", "--json", str(out_path)],
                cwd=str(project_root),
            )
            return result.returncode

        return 0

    finally:
        ib.disconnect()


if __name__ == "__main__":
    sys.exit(main())
