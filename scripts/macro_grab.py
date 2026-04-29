"""
macro_grab.py — Fetch macro indicators (VIX, SPX, DXY, 10Y, USD/SGD)
via yfinance and append to the `macro` sheet.

This is what feeds the Risk Pulse card on the PWA Home tab.

Usage:
  python scripts/macro_grab.py           # fetch + write to sheet
  python scripts/macro_grab.py --dry     # print what would be written
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# yfinance ticker → friendly name
TICKERS = {
    "^VIX":  "vix",       # CBOE Volatility Index
    "^GSPC": "spx",       # S&P 500
    "DX-Y.NYB": "dxy",    # US Dollar Index
    "^TNX": "us_10y",     # CBOE 10-year Treasury yield (note: in tenths of a point)
    "USDSGD=X": "usd_sgd",
}


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "macro-grab.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("macro-grab")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            fh = logging.FileHandler(log_path)
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(fh)
        except OSError:
            pass
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


def fetch_macro(logger: logging.Logger) -> dict[str, float]:
    """Pull each indicator's latest close via yfinance.download (1-day intraday)."""
    import yfinance as yf

    syms = list(TICKERS.keys())
    logger.info(f"Fetching {len(syms)} macro indicators: {syms}")
    raw = yf.download(
        tickers=syms,
        period="2d",
        interval="1h",
        progress=False,
        auto_adjust=True,
        threads=True,
    )

    out: dict[str, float] = {}
    if raw.empty:
        logger.error("yfinance returned empty frame")
        return out

    # Multi-ticker → multi-level columns
    if hasattr(raw.columns, "levels"):
        close = raw["Close"]
        for sym in syms:
            if sym in close.columns:
                series = close[sym].dropna()
                if not series.empty:
                    val = float(series.iloc[-1])
                    field = TICKERS[sym]
                    out[field] = val
    else:
        # Single-ticker fallback (only one survived)
        if "Close" in raw.columns:
            series = raw["Close"].dropna()
            if not series.empty:
                field = TICKERS[syms[0]]
                val = float(series.iloc[-1])
                out[field] = val

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="Print what would be written, no sheet change")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== macro-grab start ===")

    values = fetch_macro(logger)
    if not values:
        logger.error("No macro values fetched — aborting")
        return 1

    for k, v in values.items():
        logger.info(f"  {k:10}={v:.4f}")

    if args.dry:
        logger.info("[DRY] Would append to macro sheet")
        return 0

    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.MacroRow.TAB_NAME, S.MacroRow.HEADERS)

    today_iso = datetime.now().strftime("%Y-%m-%d")
    row = S.MacroRow(
        date=today_iso,
        vix=values.get("vix", 0.0),
        dxy=values.get("dxy", 0.0),
        us_10y=values.get("us_10y", 0.0),
        spx=values.get("spx", 0.0),
        usd_sgd=values.get("usd_sgd", 0.0),
    )
    sh.append_row(client, S.MacroRow.TAB_NAME, row.to_row())
    logger.info(f"✓ Appended macro row to {S.MacroRow.TAB_NAME}")
    logger.info("=== macro-grab done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
