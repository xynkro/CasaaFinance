"""
options_refresh.py — Refresh price/UPL/moneyness on KNOWN open option
positions via yfinance. Does NOT discover new positions (that requires IBKR).

Strategy: read the latest snapshot of `options` sheet, fetch the current
underlying price for each unique ticker via yfinance, recompute moneyness +
DTE, and append fresh rows. The mark price (option's `last`) is harder to
get reliably from yfinance for specific contracts, so we focus on:
  - underlying_last  → fresh from yfinance
  - dte              → recomputed from today's date
  - moneyness        → recomputed from underlying vs strike
  - last (option)    → re-fetched if option chain available

When IBKR is connected, ibkr_grab.py owns this tab — when off, this script
keeps the data alive at hourly cadence so the PWA isn't showing 18h-old
positions.

Usage:
  python scripts/options_refresh.py           # live refresh
  python scripts/options_refresh.py --dry     # print, no write
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("options-refresh")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _parse_iso_expiry(s: str) -> date | None:
    """Accept 'YYYYMMDD' (IBKR format) or 'YYYY-MM-DD'."""
    s = s.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="Print, no sheet write")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== options-refresh start ===")

    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    # Read latest snapshot of options
    ws = ss.worksheet("options")
    rows = ws.get_all_values()
    if len(rows) < 2:
        logger.warning("No options rows to refresh")
        return 0

    headers = rows[0]
    data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
    latest_date = max(r.get("date", "") for r in data)
    latest_options = [r for r in data if r.get("date") == latest_date]
    logger.info(f"Latest snapshot: {latest_date} ({len(latest_options)} positions)")

    # Get unique underlying tickers
    tickers = sorted({r["ticker"] for r in latest_options if r.get("ticker")})
    logger.info(f"Underlyings to refresh: {', '.join(tickers)}")

    # Fetch current prices
    import yfinance as yf
    raw = yf.download(
        tickers=tickers,
        period="1d",
        interval="1m",
        progress=False,
        auto_adjust=True,
        threads=True,
    )
    underlying_prices: dict[str, float] = {}
    if not raw.empty:
        if hasattr(raw.columns, "levels"):
            close = raw["Close"]
            for sym in tickers:
                if sym in close.columns:
                    series = close[sym].dropna()
                    if not series.empty:
                        underlying_prices[sym] = float(series.iloc[-1])
        else:
            if "Close" in raw.columns:
                series = raw["Close"].dropna()
                if not series.empty:
                    underlying_prices[tickers[0]] = float(series.iloc[-1])

    today = date.today()
    now_ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    refreshed_rows: list[list[str]] = []

    for pos in latest_options:
        ticker = pos.get("ticker", "").strip()
        right  = pos.get("right", "").strip().upper()
        strike = float(pos.get("strike", "0") or 0)
        expiry = pos.get("expiry", "").strip()
        qty    = float(pos.get("qty", "0") or 0)
        credit = float(pos.get("credit", "0") or 0)

        underlying_last = underlying_prices.get(ticker, 0.0)
        if underlying_last <= 0:
            logger.warning(f"  {ticker}: no underlying price — keeping old row")
            new_row = list(rows[0])  # placeholder
            for i, h in enumerate(headers):
                new_row[i] = pos.get(h, "")
            new_row[0] = now_ts
            refreshed_rows.append(new_row)
            continue

        # Recompute moneyness
        if right == "P":
            in_money = underlying_last < strike
        elif right == "C":
            in_money = underlying_last > strike
        else:
            in_money = False
        moneyness = "ITM" if in_money else "OTM"

        # Recompute DTE
        exp_date = _parse_iso_expiry(expiry)
        dte = (exp_date - today).days if exp_date else int(pos.get("dte", "0") or 0)

        # Build refreshed row preserving original schema order
        out: list[str] = []
        for h in headers:
            v = pos.get(h, "")
            if h == "date":
                v = now_ts
            elif h == "underlying_last":
                v = f"{underlying_last:.2f}"
            elif h == "moneyness":
                v = moneyness
            elif h == "dte":
                v = str(max(0, dte))
            out.append(v)
        refreshed_rows.append(out)

        logger.info(
            f"  {ticker:6} {right} ${strike:.2f} exp={expiry} dte={dte:3} "
            f"underlying=${underlying_last:7.2f} {moneyness}"
        )

    if args.dry:
        logger.info(f"[DRY] Would append {len(refreshed_rows)} rows")
        return 0

    ws.append_rows(refreshed_rows, value_input_option="USER_ENTERED")
    logger.info(f"✓ Appended {len(refreshed_rows)} refreshed option rows")
    logger.info("=== options-refresh done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
