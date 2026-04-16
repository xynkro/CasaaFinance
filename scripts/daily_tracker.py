"""
daily_tracker.py — Fetch current prices from Yahoo Finance using last-known
positions, calculate portfolio values, and push daily snapshots + macro to the
Sheet.  No IBKR connection needed — just internet.

How it works:
  1. Reads the most recent PortfolioGrab JSON for holdings (tickers, qty, avg_cost)
     and last-known cash balances.
  2. Fetches live prices via yfinance for every ticker.
  3. Calculates mkt_val, UPL, net_liq per account.
  4. Fetches macro data (VIX, SPX, DXY, US 10Y, USD/SGD).
  5. Pushes snapshot_caspar, snapshot_sarah, positions_caspar, positions_sarah,
     and macro rows to the Sheet.

Usage:
  python scripts/daily_tracker.py              # fetch + push
  python scripts/daily_tracker.py --dryrun     # fetch + print, no push
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GRAB_DIR = ROOT / "PortfolioGrabs"

# SGX tickers need .SI suffix for Yahoo Finance
SGX_TICKERS = {"C6L", "G3B", "ES3"}

# Macro symbols on Yahoo Finance
MACRO_SYMBOLS = {
    "vix":     "^VIX",
    "spx":     "^GSPC",
    "dxy":     "DX-Y.NYB",
    "us_10y":  "^TNX",
    "usd_sgd": "USDSGD=X",
}


def yahoo_ticker(symbol: str) -> str:
    """Convert our ticker to Yahoo Finance symbol."""
    s = symbol.upper()
    if s in SGX_TICKERS:
        return f"{s}.SI"
    return s


def find_latest_grab() -> Path | None:
    """Find the most recent PortfolioGrab JSON."""
    if not GRAB_DIR.exists():
        return None
    grabs = sorted(GRAB_DIR.glob("*_PortfolioGrab.json"))
    return grabs[-1] if grabs else None


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current/last-close prices for a list of tickers via yfinance."""
    import yfinance as yf

    yahoo_syms = [yahoo_ticker(t) for t in tickers]
    result: dict[str, float] = {}

    # Batch download — much faster than one-by-one
    data = yf.download(yahoo_syms, period="1d", progress=False, threads=True)

    if data.empty:
        print("  Warning: yfinance returned no data")
        return result

    # yf.download returns a DataFrame with MultiIndex columns when multiple tickers
    close = data.get("Close")
    if close is None:
        return result

    for orig, ysym in zip(tickers, yahoo_syms):
        try:
            if len(yahoo_syms) == 1:
                # Single ticker: Close is a Series
                val = float(close.dropna().iloc[-1])
            else:
                # Multi ticker: Close is a DataFrame with ticker columns
                col = close[ysym] if ysym in close.columns else None
                if col is not None:
                    val = float(col.dropna().iloc[-1])
                else:
                    val = 0.0
            result[orig] = val
        except (KeyError, IndexError):
            print(f"  Warning: no price for {orig} ({ysym})")
            result[orig] = 0.0

    return result


def fetch_macro() -> dict[str, float]:
    """Fetch macro indicators from Yahoo Finance."""
    import yfinance as yf

    symbols = list(MACRO_SYMBOLS.values())
    result: dict[str, float] = {}

    data = yf.download(symbols, period="1d", progress=False, threads=True)
    if data.empty:
        return result

    close = data.get("Close")
    if close is None:
        return result

    for key, ysym in MACRO_SYMBOLS.items():
        try:
            if len(symbols) == 1:
                val = float(close.dropna().iloc[-1])
            else:
                col = close[ysym] if ysym in close.columns else None
                val = float(col.dropna().iloc[-1]) if col is not None else 0.0
            result[key] = round(val, 4)
        except (KeyError, IndexError):
            result[key] = 0.0

    return result


def build_snapshots(grab: dict, prices: dict[str, float], macro: dict[str, float]):
    """Build schema rows from grab + live prices."""
    from src import schema as S

    date = datetime.now().strftime("%Y-%m-%d")
    usd_sgd = macro.get("usd_sgd", 1.0) or 1.0

    results = {"date": date}

    for acct_key, snap_cls, pos_tab in [
        ("caspar", S.SnapshotCaspar, "positions_caspar"),
        ("sarah",  S.SnapshotSarah, "positions_sarah"),
    ]:
        acct = grab.get("accounts", {}).get(acct_key, {})
        summary = acct.get("summary", {})
        positions_raw = acct.get("positions", [])

        # Cash: use last known value
        if acct_key == "caspar":
            cash = float(summary.get("total_cash", 0))
        else:
            cash = float(summary.get("total_cash_sgd", 0))

        # Build position rows with live prices
        pos_rows = []
        total_mkt_val = 0.0
        total_upl = 0.0

        for p in positions_raw:
            symbol = p.get("symbol", "")
            qty = float(p.get("qty", 0))
            avg_cost = float(p.get("avg_cost", 0))
            last = prices.get(symbol, float(p.get("last", 0)))

            # For SGX stocks in Sarah's account: price is in SGD already from Yahoo .SI
            # For US stocks in Sarah's account: price is in USD, mkt_val in USD
            # Sarah's net_liq is reported in SGD by IBKR — we'll approximate by
            # converting USD positions using usd_sgd rate
            mkt_val = qty * last
            upl = (last - avg_cost) * qty

            # Sarah: convert USD-denominated positions to SGD for aggregation
            if acct_key == "sarah" and symbol not in SGX_TICKERS:
                mkt_val_sgd = mkt_val * usd_sgd
                upl_sgd = upl * usd_sgd
            else:
                mkt_val_sgd = mkt_val
                upl_sgd = upl

            if acct_key == "sarah":
                total_mkt_val += mkt_val_sgd
                total_upl += upl_sgd
            else:
                total_mkt_val += mkt_val
                total_upl += upl

            pos_rows.append(S.PositionRow(
                date=date,
                ticker=symbol,
                qty=qty,
                avg_cost=avg_cost,
                last=last,
                mkt_val=mkt_val,
                upl=upl,
                weight=0.0,  # calculated after net_liq is known
            ))

        net_liq = total_mkt_val + cash
        upl_pct = total_upl / net_liq if net_liq else 0.0

        # Back-fill weights
        for pr in pos_rows:
            if net_liq > 0:
                pr.weight = abs(pr.mkt_val) / net_liq if acct_key == "caspar" else abs(pr.mkt_val * (usd_sgd if pr.ticker not in SGX_TICKERS else 1.0)) / net_liq

        if acct_key == "caspar":
            snap = S.SnapshotCaspar(date=date, net_liq_usd=net_liq, cash=cash, upl=total_upl, upl_pct=upl_pct)
        else:
            snap = S.SnapshotSarah(date=date, net_liq_sgd=net_liq, cash_sgd=cash, upl_sgd=total_upl, upl_pct=upl_pct)

        results[f"snap_{acct_key}"] = snap
        results[f"pos_{acct_key}"] = pos_rows

    # Macro row
    results["macro"] = S.MacroRow(
        date=date,
        vix=macro.get("vix"),
        dxy=macro.get("dxy"),
        us_10y=macro.get("us_10y"),
        spx=macro.get("spx"),
        usd_sgd=macro.get("usd_sgd"),
    )

    return results


def push_to_sheet(results: dict):
    """Push all rows to sheet."""
    from src import schema as S, sheets as sh
    from src.sync import load_env
    load_env()
    client = sh.authenticate()

    snap_c = results["snap_caspar"]
    sh.ensure_headers(client, S.SnapshotCaspar.TAB_NAME, S.SnapshotCaspar.HEADERS)
    sh.append_row(client, S.SnapshotCaspar.TAB_NAME, snap_c.to_row())

    pos_c = results["pos_caspar"]
    sh.ensure_headers(client, "positions_caspar", S.PositionRow.HEADERS)
    sh.append_rows(client, "positions_caspar", [p.to_row() for p in pos_c])

    snap_s = results["snap_sarah"]
    sh.ensure_headers(client, S.SnapshotSarah.TAB_NAME, S.SnapshotSarah.HEADERS)
    sh.append_row(client, S.SnapshotSarah.TAB_NAME, snap_s.to_row())

    pos_s = results["pos_sarah"]
    sh.ensure_headers(client, "positions_sarah", S.PositionRow.HEADERS)
    sh.append_rows(client, "positions_sarah", [p.to_row() for p in pos_s])

    macro = results["macro"]
    sh.ensure_headers(client, S.MacroRow.TAB_NAME, S.MacroRow.HEADERS)
    sh.append_row(client, S.MacroRow.TAB_NAME, macro.to_row())

    print(f"  Pushed: snapshot_caspar, {len(pos_c)} caspar positions, "
          f"snapshot_sarah, {len(pos_s)} sarah positions, macro")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dryrun", action="store_true", help="Fetch and print only, don't push to sheet")
    ap.add_argument("--grab", type=str, help="Path to specific grab JSON (default: latest)")
    args = ap.parse_args()

    # Find grab file
    if args.grab:
        grab_path = Path(args.grab)
    else:
        grab_path = find_latest_grab()
    if not grab_path or not grab_path.exists():
        print(f"No grab file found in {GRAB_DIR}")
        print("Run `python src/ibkr_grab.py` at least once to capture positions.")
        return 1

    print(f"Using positions from: {grab_path.name}")
    grab = json.loads(grab_path.read_text())

    # Collect all tickers
    all_tickers = set()
    for acct in ("caspar", "sarah"):
        for p in grab.get("accounts", {}).get(acct, {}).get("positions", []):
            all_tickers.add(p["symbol"])

    print(f"Fetching prices for {len(all_tickers)} tickers...")
    prices = fetch_prices(list(all_tickers))
    print(f"  Got prices for {sum(1 for v in prices.values() if v > 0)}/{len(all_tickers)} tickers")

    print("Fetching macro data...")
    macro = fetch_macro()
    for k, v in macro.items():
        print(f"  {k}: {v}")

    print("Building snapshots...")
    results = build_snapshots(grab, prices, macro)

    snap_c = results["snap_caspar"]
    snap_s = results["snap_sarah"]
    print(f"  Caspar: net_liq=${snap_c.net_liq_usd:,.2f}  upl=${snap_c.upl:,.2f}  ({snap_c.upl_pct*100:.2f}%)")
    print(f"  Sarah:  net_liq=S${snap_s.net_liq_sgd:,.2f}  upl=S${snap_s.upl_sgd:,.2f}  ({snap_s.upl_pct*100:.2f}%)")

    if args.dryrun:
        print("\n--dryrun: not pushing to sheet.")
        return 0

    print("\nPushing to sheet...")
    push_to_sheet(results)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
