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
  5. Builds options rows with moneyness, DTE, assignment risk, wheel stage.
  6. Pushes snapshot, positions, options, and macro rows to the Sheet.

Usage:
  python scripts/daily_tracker.py              # fetch + push
  python scripts/daily_tracker.py --dryrun     # fetch + print, no push
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, date
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


def calc_moneyness(right: str, strike: float, underlying: float) -> str:
    """Calculate ITM/ATM/OTM based on option type and underlying price."""
    if underlying <= 0 or strike <= 0:
        return "?"
    pct_diff = abs(underlying - strike) / strike
    if pct_diff < 0.02:  # within 2% of strike
        return "ATM"
    if right == "C":
        return "ITM" if underlying > strike else "OTM"
    else:  # put
        return "ITM" if underlying < strike else "OTM"


def calc_dte(expiry: str) -> int:
    """Days to expiry from YYYYMMDD string."""
    try:
        exp_date = datetime.strptime(expiry, "%Y%m%d").date()
        return max(0, (exp_date - date.today()).days)
    except (ValueError, TypeError):
        return -1


def calc_assignment_risk(moneyness: str, dte: int, trend_risk: str = "") -> str:
    """Assignment risk based on moneyness + time to expiry + trend."""
    if moneyness == "ITM":
        if dte <= 7 or trend_risk == "BREACHING":
            return "HIGH"
        elif dte <= 21 or trend_risk == "CONVERGING":
            return "MED"
        else:
            return "LOW"
    elif moneyness == "ATM":
        if dte <= 7 or trend_risk in ("BREACHING", "CONVERGING"):
            return "MED"
        else:
            return "LOW"
    elif trend_risk == "CONVERGING" and dte <= 14:
        return "MED"
    return "LOW"  # OTM


def fetch_momentum(tickers: list[str]) -> dict[str, float]:
    """Fetch 5-day rate of change for option underlyings."""
    import yfinance as yf

    if not tickers:
        return {}

    yahoo_syms = [yahoo_ticker(t) for t in tickers]
    result: dict[str, float] = {}

    data = yf.download(yahoo_syms, period="1mo", progress=False, threads=True)
    if data.empty:
        return result

    close = data.get("Close")
    if close is None:
        return result

    for orig, ysym in zip(tickers, yahoo_syms):
        try:
            if len(yahoo_syms) == 1:
                series = close.dropna()
            else:
                col = close[ysym] if ysym in close.columns else None
                series = col.dropna() if col is not None else None

            if series is not None and len(series) >= 6:
                # 5-day rate of change: (today - 5 days ago) / 5 days ago
                roc = (float(series.iloc[-1]) - float(series.iloc[-6])) / float(series.iloc[-6])
                result[orig] = round(roc * 100, 2)  # as percentage
            else:
                result[orig] = 0.0
        except (KeyError, IndexError):
            result[orig] = 0.0

    return result


def calc_trend_risk(right: str, strike: float, underlying: float, momentum_5d: float, is_short: bool) -> str:
    """Assess whether price momentum is pushing toward assignment."""
    if underlying <= 0 or strike <= 0:
        return "?"
    dist_pct = (underlying - strike) / strike * 100  # positive = above strike

    if is_short:
        # Short call: danger if price trending UP toward/past strike
        if right == "C":
            if dist_pct > 2 and momentum_5d > 1:        # already ITM & going deeper
                return "BREACHING"
            elif dist_pct > -5 and momentum_5d > 1.5:    # close & accelerating up
                return "CONVERGING"
            elif momentum_5d > 2 and dist_pct > -10:     # strong uptrend
                return "DRIFTING"
            return "SAFE"
        # Short put: danger if price trending DOWN toward/past strike
        else:
            if dist_pct < -2 and momentum_5d < -1:       # already ITM & going deeper
                return "BREACHING"
            elif dist_pct < 5 and momentum_5d < -1.5:    # close & accelerating down
                return "CONVERGING"
            elif momentum_5d < -2 and dist_pct < 10:     # strong downtrend
                return "DRIFTING"
            return "SAFE"
    else:
        # Long positions: reverse logic (you WANT ITM)
        if right == "C":
            if dist_pct > 2 and momentum_5d > 0:
                return "SAFE"          # profitable & trending right
            elif momentum_5d < -1.5:
                return "DRIFTING"      # moving away from profit
            return "SAFE"
        else:
            if dist_pct < -2 and momentum_5d < 0:
                return "SAFE"
            elif momentum_5d > 1.5:
                return "DRIFTING"
            return "SAFE"


def build_options(grab: dict, prices: dict[str, float], momentum: dict[str, float], today: str):
    """Build option rows with moneyness, wheel stage, and adjusted cost basis."""
    from src import schema as S

    option_rows = []

    for acct_key in ("caspar", "sarah"):
        acct = grab.get("accounts", {}).get(acct_key, {})
        options_raw = acct.get("options", [])
        positions_raw = acct.get("positions", [])

        if not options_raw:
            continue

        # Build stock holdings map: ticker -> {qty, avg_cost}
        stock_map = {}
        for p in positions_raw:
            sym = p.get("symbol", "")
            stock_map[sym] = {
                "qty": float(p.get("qty", 0)),
                "avg_cost": float(p.get("avg_cost", 0)),
            }

        # Accumulate total credits per ticker from current options
        # (for adj_cost_basis = stock_avg_cost - premiums_per_share)
        ticker_credits: dict[str, float] = {}
        for opt in options_raw:
            sym = opt.get("symbol", "")
            credit = float(opt.get("avg_cost_credit", 0))
            mult = int(opt.get("multiplier", 100))
            # credit is per-share cost from IBKR (avg_cost_credit / multiplier gives per-share premium)
            credit_per_share = credit / mult if mult else credit / 100
            if opt.get("qty", 0) < 0:  # short = sold = credit received
                ticker_credits[sym] = ticker_credits.get(sym, 0) + credit_per_share

        for opt in options_raw:
            sym = opt.get("symbol", "")
            right = opt.get("right", "C")
            strike = float(opt.get("strike", 0))
            expiry = opt.get("expiry", "")
            qty = float(opt.get("qty", 0))
            credit = float(opt.get("avg_cost_credit", 0))
            mult = int(opt.get("multiplier", 100))
            last_opt = float(opt.get("last", 0))
            mkt_val = float(opt.get("mkt_val", 0))
            upl = float(opt.get("upl", 0))

            # Underlying price from Yahoo (live)
            underlying_last = prices.get(sym, 0.0)

            moneyness = calc_moneyness(right, strike, underlying_last)
            dte = calc_dte(expiry)
            is_short = qty < 0
            mom_5d = momentum.get(sym, 0.0)
            trend = calc_trend_risk(right, strike, underlying_last, mom_5d, is_short)
            assignment_risk = calc_assignment_risk(moneyness, dte, trend)

            # Determine wheel leg
            has_stock = sym in stock_map and stock_map[sym]["qty"] > 0
            if qty < 0 and right == "C" and has_stock:
                wheel_leg = "CC"  # covered call
            elif qty < 0 and right == "P":
                wheel_leg = "CSP"  # cash-secured put
            elif qty < 0 and right == "C" and not has_stock:
                wheel_leg = "NAKED_CALL"
            elif qty > 0 and right == "C":
                wheel_leg = "LONG_CALL"
            elif qty > 0 and right == "P":
                wheel_leg = "LONG_PUT"
            else:
                wheel_leg = "OTHER"

            # Adjusted cost basis: stock avg_cost - premiums collected
            stock_info = stock_map.get(sym)
            if stock_info and stock_info["qty"] > 0:
                total_credit_per_share = ticker_credits.get(sym, 0)
                adj_cost_basis = stock_info["avg_cost"] - total_credit_per_share
            else:
                adj_cost_basis = 0.0

            option_rows.append(S.OptionRow(
                date=today,
                account=acct_key,
                ticker=sym,
                right=right,
                strike=strike,
                expiry=expiry,
                qty=qty,
                credit=credit / mult if mult else credit / 100,
                last=last_opt,
                mkt_val=mkt_val,
                upl=upl,
                underlying_last=underlying_last,
                moneyness=moneyness,
                dte=dte,
                assignment_risk=assignment_risk,
                wheel_leg=wheel_leg,
                adj_cost_basis=adj_cost_basis,
                momentum_5d=mom_5d,
                trend_risk=trend,
            ))

    return option_rows


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

    # Options
    opts = results.get("options", [])
    if opts:
        sh.ensure_headers(client, S.OptionRow.TAB_NAME, S.OptionRow.HEADERS)
        sh.append_rows(client, S.OptionRow.TAB_NAME, [o.to_row() for o in opts])

    macro = results["macro"]
    sh.ensure_headers(client, S.MacroRow.TAB_NAME, S.MacroRow.HEADERS)
    sh.append_row(client, S.MacroRow.TAB_NAME, macro.to_row())

    print(f"  Pushed: snapshot_caspar, {len(pos_c)} caspar positions, "
          f"snapshot_sarah, {len(pos_s)} sarah positions, "
          f"{len(opts)} options, macro")


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

    # Collect all tickers (stocks + option underlyings)
    all_tickers = set()
    for acct in ("caspar", "sarah"):
        acct_data = grab.get("accounts", {}).get(acct, {})
        for p in acct_data.get("positions", []):
            all_tickers.add(p["symbol"])
        for o in acct_data.get("options", []):
            all_tickers.add(o["symbol"])  # underlying ticker

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

    # Fetch momentum for option underlyings
    option_underlyings = set()
    for acct in ("caspar", "sarah"):
        for o in grab.get("accounts", {}).get(acct, {}).get("options", []):
            option_underlyings.add(o["symbol"])

    momentum = {}
    if option_underlyings:
        print(f"Fetching momentum for {len(option_underlyings)} option underlyings...")
        momentum = fetch_momentum(list(option_underlyings))
        for sym, roc in momentum.items():
            print(f"  {sym}: {roc:+.2f}% (5d)")

    # Build options
    print("Building options...")
    today = results["date"]
    option_rows = build_options(grab, prices, momentum, today)
    results["options"] = option_rows
    for opt in option_rows:
        exp_fmt = f"{opt.expiry[:4]}-{opt.expiry[4:6]}-{opt.expiry[6:]}" if len(opt.expiry) == 8 else opt.expiry
        print(f"  {opt.account}: {opt.ticker} {opt.strike}{opt.right} exp {exp_fmt} "
              f"| {opt.moneyness} | DTE {opt.dte} | risk {opt.assignment_risk} | {opt.wheel_leg}"
              f"{f' | adj_basis ${opt.adj_cost_basis:.2f}' if opt.adj_cost_basis else ''}")

    if args.dryrun:
        print("\n--dryrun: not pushing to sheet.")
        return 0

    print("\nPushing to sheet...")
    push_to_sheet(results)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
