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


def spx_above_200dma_from_closes(closes: list[float]) -> bool | None:
    """SPX close vs its 200-day SMA from a daily close series (oldest→newest).
    None when there isn't enough history to verify — callers write '' so
    downstream consumers degrade to reduced sizing rather than assuming TRUE."""
    closes = [c for c in closes if c is not None]
    if len(closes) < 200:
        return None
    sma200 = sum(closes[-200:]) / 200.0
    return closes[-1] > sma200


def fetch_spx_above_200dma(logger: logging.Logger) -> bool | None:
    """Daily SPX closes (250d) → close vs 200-day SMA. None on ANY failure —
    never a guessed default. This feeds the `spx_above_200sma` macro column the
    paper executor + macro gate read as the trend-halt input."""
    try:
        import yfinance as yf
        data = yf.download("^GSPC", period="250d", progress=False, auto_adjust=True)
        if data is None or data.empty:
            logger.warning("spx_above_200sma: yfinance returned empty ^GSPC frame")
            return None
        close = data["Close"]
        if hasattr(close, "columns"):       # MultiIndex single-ticker shape
            close = close.iloc[:, 0]
        return spx_above_200dma_from_closes([float(v) for v in close.dropna().tolist()])
    except Exception as e:
        logger.warning(f"spx_above_200sma fetch failed: {e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="Print what would be written, no sheet change")
    args = ap.parse_args()

    # FileHandler is best-effort (read-only cloud FS degrades to stderr-only).
    from src.logging_util import setup_file_logging
    logger = setup_file_logging("macro-grab", ".state/macro-grab.log", file_optional=True)
    logger.info("=== macro-grab start ===")

    values = fetch_macro(logger)
    if not values:
        logger.error("No macro values fetched — aborting")
        return 1

    for k, v in values.items():
        logger.info(f"  {k:10}={v:.4f}")

    spx_above = fetch_spx_above_200dma(logger)
    logger.info(f"  spx_above_200sma={spx_above}")

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
        spx_above_200sma=spx_above,
    )
    sh.append_row(client, S.MacroRow.TAB_NAME, row.to_row())
    logger.info(f"✓ Appended macro row to {S.MacroRow.TAB_NAME}")
    logger.info("=== macro-grab done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
