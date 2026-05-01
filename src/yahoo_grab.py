"""
yahoo_grab.py — Fetch current prices from Yahoo Finance and refresh
the positions + snapshot sheets. IBKR-free alternative to ibkr_grab.

Usage:
  python src/yahoo_grab.py           # update both accounts
  python src/yahoo_grab.py --dry     # print what would be written, no sheet writes
  python src/yahoo_grab.py --caspar  # only Caspar
  python src/yahoo_grab.py --sarah   # only Sarah

Notes:
  - Prices are 15-min delayed (Yahoo Finance free tier)
  - SGX stocks use .SI suffix on Yahoo (C6L → C6L.SI, G3B → G3B.SI)
  - Net liquidity = sum(position values) + last known cash balance
  - Cash balance is not fetched — last IBKR cash figure is reused
  - Options positions are NOT updated (no IBKR = no options chain data)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── SGX tickers that need .SI suffix on Yahoo Finance ────────────────────────
SGX_TICKERS: set[str] = {"C6L", "G3B", "D05", "O39", "U11", "Z74", "V03"}

# ── Account → sheet tab names ────────────────────────────────────────────────
ACCOUNTS = {
    "caspar": {
        "pos_tab":      "positions_caspar",
        "snap_tab":     "snapshot_caspar",
        "snap_key":     "net_liq_usd",
        "cash_key":     "cash",
        "currency":     "USD",
    },
    "sarah": {
        "pos_tab":      "positions_sarah",
        "snap_tab":     "snapshot_sarah",
        "snap_key":     "net_liq_sgd",
        "cash_key":     "cash_sgd",
        "currency":     "SGD",
    },
}


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "yahoo-grab.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("yahoo-grab")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


def _yahoo_symbol(ticker: str) -> str:
    """Convert internal ticker → Yahoo Finance symbol."""
    if ticker in SGX_TICKERS:
        return f"{ticker}.SI"
    return ticker


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch latest prices via yfinance (handles crumb/session auth automatically)."""
    import yfinance as yf

    yahoo_symbols = [_yahoo_symbol(t) for t in tickers]
    # yf.download with period="1d" is the most reliable batch method
    raw = yf.download(
        tickers=yahoo_symbols,
        period="1d",
        interval="1m",
        progress=False,
        auto_adjust=True,
        threads=True,
    )

    result: dict[str, float] = {}

    if raw.empty:
        return result

    # Multi-ticker: columns are (field, symbol); single ticker: columns are fields
    if isinstance(raw.columns, type(raw.columns)) and hasattr(raw.columns, "levels"):
        # Multi-level columns: ('Close', 'BBAI'), ('Close', 'AAPL'), ...
        close = raw["Close"]
        for col in close.columns:
            series = close[col].dropna()
            if not series.empty:
                price = float(series.iloc[-1])
                # Strip .SI suffix to match internal ticker
                internal = str(col).replace(".SI", "")
                result[internal] = price
    else:
        # Single ticker — raw.columns are just field names
        if "Close" in raw.columns:
            series = raw["Close"].dropna()
            if not series.empty:
                ticker = yahoo_symbols[0].replace(".SI", "")
                result[ticker] = float(series.iloc[-1])

    return result


def fetch_usdsgd() -> float:
    """Fetch USD/SGD spot rate via yfinance."""
    try:
        import yfinance as yf
        fx = yf.download("USDSGD=X", period="1d", interval="1m", progress=False)
        if not fx.empty and "Close" in fx.columns:
            return float(fx["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return 1.35  # fallback


def read_latest_positions(ws, logger: logging.Logger) -> tuple[list[dict], list[str]]:
    """Read all rows from the positions worksheet, return latest-date rows + all raw rows."""
    all_rows = ws.get_all_values()
    if not all_rows:
        return [], []
    headers = all_rows[0]
    data = [dict(zip(headers, r)) for r in all_rows[1:] if any(r)]
    if not data:
        return [], headers
    latest_date = max(r.get("date", "") for r in data)
    logger.info(f"Latest position date: {latest_date}")
    return [r for r in data if r.get("date") == latest_date], headers


def refresh_account(
    account: str,
    cfg: dict,
    client,
    ss,
    prices: dict[str, float],
    usdsgd: float,
    dry: bool,
    logger: logging.Logger,
) -> None:
    ws_pos = ss.worksheet(cfg["pos_tab"])
    ws_snap = ss.worksheet(cfg["snap_tab"])

    latest_positions, headers = read_latest_positions(ws_pos, logger)
    if not latest_positions:
        logger.warning(f"No positions found for {account}")
        return

    from src.schema import now_sgt_iso
    now_ts = now_sgt_iso()  # SGT-anchored so cloud + Mac writes sort consistently
    updated_rows: list[list[str]] = []
    total_mkt_val = 0.0
    total_upl = 0.0

    for pos in latest_positions:
        ticker = pos.get("ticker", "").strip()
        if not ticker:
            continue
        try:
            qty = float(pos.get("qty", 0))
            avg_cost = float(pos.get("avg_cost", 0))
        except (ValueError, TypeError):
            continue

        price = prices.get(ticker)
        if price is None:
            logger.warning(f"  {ticker}: no price from Yahoo — keeping last={pos.get('last','?')}")
            price = float(pos.get("last", 0) or 0)

        mkt_val = qty * price
        upl = (price - avg_cost) * qty
        total_mkt_val += mkt_val
        total_upl += upl

        logger.info(f"  {ticker:8} qty={qty:6.0f}  last={price:10.4f}  mkt_val={mkt_val:10.2f}  upl={upl:+9.2f}")

        row = [
            now_ts,
            ticker,
            f"{qty:.4f}",
            f"{avg_cost:.4f}",
            f"{price:.4f}",
            f"{mkt_val:.2f}",
            f"{upl:.2f}",
            "",  # weight — filled below
        ]
        updated_rows.append(row)

    # Fill weights
    for row in updated_rows:
        try:
            mv = float(row[5])
            row[7] = f"{mv / total_mkt_val:.6f}" if total_mkt_val else "0"
        except Exception:
            row[7] = "0"

    if not dry:
        # Append new position rows (keeps history)
        ws_pos.append_rows(updated_rows, value_input_option="USER_ENTERED")
        logger.info(f"  → Wrote {len(updated_rows)} position rows to {cfg['pos_tab']}")
    else:
        logger.info(f"  [DRY] Would write {len(updated_rows)} rows to {cfg['pos_tab']}")

    # ── Snapshot update ──────────────────────────────────────────────────────
    snap_rows = ws_snap.get_all_values()
    if not snap_rows:
        logger.warning(f"No snapshot data found for {account}")
        return

    snap_headers = snap_rows[0]
    snap_data = [dict(zip(snap_headers, r)) for r in snap_rows[1:] if any(r)]
    if not snap_data:
        return
    latest_snap = max(snap_data, key=lambda r: r.get("date", ""))

    try:
        cash = float(latest_snap.get(cfg["cash_key"], 0) or 0)
    except (ValueError, TypeError):
        cash = 0.0

    if cfg["currency"] == "SGD":
        # Sarah's positions are USD, snapshot is SGD
        net_liq = total_mkt_val * usdsgd + cash
        upl_currency = total_upl * usdsgd
        net_liq_prev = net_liq - upl_currency
        upl_pct = upl_currency / net_liq_prev if net_liq_prev else 0
        snap_row = [now_ts, f"{net_liq:.2f}", f"{cash:.2f}", f"{upl_currency:.2f}", f"{upl_pct:.4f}"]
    else:
        # Caspar: USD for US stocks, SGD for SGX stocks — approximate USD value
        net_liq = total_mkt_val + cash
        net_liq_prev = net_liq - total_upl
        upl_pct = total_upl / net_liq_prev if net_liq_prev else 0
        snap_row = [now_ts, f"{net_liq:.2f}", f"{cash:.2f}", f"{total_upl:.2f}", f"{upl_pct:.4f}"]

    logger.info(f"  Snapshot: net_liq={snap_row[1]} cash={cash:.2f} upl={snap_row[3]} upl_pct={snap_row[4]}")

    if not dry:
        ws_snap.append_row(snap_row, value_input_option="USER_ENTERED")
        logger.info(f"  → Wrote snapshot row to {cfg['snap_tab']}")
    else:
        logger.info(f"  [DRY] Would write snapshot row to {cfg['snap_tab']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry",    action="store_true", help="Print what would be written, no sheet changes")
    ap.add_argument("--caspar", action="store_true", help="Only update Caspar's account")
    ap.add_argument("--sarah",  action="store_true", help="Only update Sarah's account")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== yahoo-grab start ===")

    target_accounts = list(ACCOUNTS.keys())
    if args.caspar and not args.sarah:
        target_accounts = ["caspar"]
    elif args.sarah and not args.caspar:
        target_accounts = ["sarah"]

    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    # Collect all tickers from both accounts
    all_tickers: list[str] = []
    for account in target_accounts:
        cfg = ACCOUNTS[account]
        ws = ss.worksheet(cfg["pos_tab"])
        all_rows = ws.get_all_values()
        if len(all_rows) < 2:
            continue
        headers = all_rows[0]
        data = [dict(zip(headers, r)) for r in all_rows[1:] if any(r)]
        if not data:
            continue
        latest_date = max(r.get("date", "") for r in data)
        latest = [r for r in data if r.get("date") == latest_date]
        for pos in latest:
            t = pos.get("ticker", "").strip()
            if t and t not in all_tickers:
                all_tickers.append(t)

    if not all_tickers:
        logger.error("No tickers found in any position sheet")
        return 1

    logger.info(f"Fetching prices for: {', '.join(all_tickers)}")
    try:
        prices = fetch_prices(all_tickers)
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    missing = [t for t in all_tickers if t not in prices]
    if missing:
        logger.warning(f"No price returned for: {', '.join(missing)}")

    for t, p in sorted(prices.items()):
        logger.info(f"  Price: {t:10} = {p:.4f}")

    usdsgd = fetch_usdsgd()
    logger.info(f"USD/SGD: {usdsgd:.4f}")

    for account in target_accounts:
        logger.info(f"--- {account.upper()} ---")
        refresh_account(account, ACCOUNTS[account], client, ss, prices, usdsgd, args.dry, logger)

    logger.info("=== yahoo-grab done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
