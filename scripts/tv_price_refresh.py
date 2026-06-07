"""
tv_price_refresh.py — 5-minute live-price feed via TradingView's public
scanner endpoint.

What this fixes
---------------
The PWA Portfolio used to show whatever `last` price was captured by the
hourly Yahoo Grab cron, so the displayed mkt_val / UPL could be 15+ min
stale during US market hours. This script writes a single upserted row
per portfolio ticker into the `live_prices` sheet, refreshed every 5 min.
The PWA overlays `live_prices.last` onto the positions data so the user
sees near-realtime numbers even when no IBKR or Yahoo grab has run.

Why TradingView, not Yahoo
--------------------------
- Same endpoint we already use for `tv_signals` daily — proven reliable.
- Single batched POST returns all tickers in one request.
- TV updates near-realtime during US market hours.
- No CORS/IP throttling issues seen with Yahoo's chart endpoint.

Architecture
------------
- Read latest portfolio tickers from `positions_caspar` + `positions_sarah`.
- Group by exchange (NASDAQ / NYSE / AMEX) — SGX symbols routed to a
  Yahoo fallback because TV `america` screener doesn't include SGX.
- POST a single batch to `scanner.tradingview.com/america/scan` for the
  US tickers; columns = [close, change, volume].
- For SGX tickers: fall back to yfinance (cheap, ~3-5 tickers).
- UPSERT into `live_prices` keyed by `ticker` (one row per ticker total).
- All timestamps SGT-anchored via S.now_sgt_iso().

Usage
-----
  python scripts/tv_price_refresh.py            # live — upserts to sheet
  python scripts/tv_price_refresh.py --dry      # parse only; no sheet write

Schedule
--------
GitHub Actions cron `*/5 * * * *` — see `.github/workflows/tv-prices.yml`.
Off-hours runs are mostly idempotent (close prices don't change) but the
cost is trivial (~30 row upserts/run, ~5s wall time).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402

# Imports after sys.path fix — must come AFTER the path insert above.
# The src package isn't importable without this.
from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402

# --- TradingView scanner ----------------------------------------------------

TV_ENDPOINT = "https://scanner.tradingview.com/america/scan"
TV_COLUMNS = ["close", "change", "volume"]

# Default exchange for tickers we haven't classified. Falls back to a probe
# of multiple exchanges if a ticker isn't returned on the first attempt.
EXCHANGE_PROBE_ORDER = ["NASDAQ", "NYSE", "AMEX"]

# Hand-curated overrides — symbols whose primary exchange differs from
# what alphabetical/heuristic guessing would pick. Keep this small; the
# probe loop handles the rest. Source: tv_signals_run.py (single source
# of truth for our universe's exchange map).
TICKER_EXCHANGE: dict[str, str] = {
    "AAPL": "NASDAQ", "AMD": "NASDAQ", "AMZN": "NASDAQ",
    "BBAI": "NASDAQ", "BTBT": "NASDAQ", "BYND": "NASDAQ",
    "GOOGL": "NASDAQ", "GLDM": "AMEX", "HIMS": "NYSE",
    "INTC": "NASDAQ", "META": "NASDAQ", "MDLZ": "NASDAQ",
    "MSFT": "NASDAQ", "NFLX": "NASDAQ", "NVDA": "NASDAQ",
    "OPEN": "NYSE", "PEP": "NASDAQ", "QQQ": "NASDAQ",
    "RCAT": "NASDAQ", "SBET": "NASDAQ", "SCHD": "AMEX",
    "SLV": "AMEX", "SPY": "AMEX", "SSO": "AMEX",
    "TQQQ": "NASDAQ", "WIX": "NASDAQ",
    "JPM": "NYSE", "MA": "NYSE", "MDT": "NYSE",
    "PM": "NYSE", "UNH": "NYSE", "V": "NYSE",
    "TLT": "NASDAQ", "IEF": "NASDAQ", "EDV": "NYSE",
    "VEA": "NYSE", "VIXM": "AMEX", "XLP": "AMEX",
    "AGG": "NASDAQ", "DBC": "AMEX", "UVXY": "AMEX",
    "ZROZ": "AMEX", "VGLT": "NASDAQ", "IAU": "AMEX",
}

# SGX tickers — fall back to yfinance with `.SI` suffix.
SGX_TICKERS = {"C6L", "G3B", "ES3"}


# --- universe ---------------------------------------------------------------

def read_portfolio_tickers(client, logger: logging.Logger) -> set[str]:
    """Pull tickers from the latest date in positions_caspar + positions_sarah."""
    out: set[str] = set()
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            ss = sh._open_sheet(client)
            rows = ss.worksheet(tab).get_all_values()
        except Exception as e:
            logger.warning(f"  [universe] {tab} read failed: {e}")
            continue
        if len(rows) <= 1:
            continue
        # Latest date prefix only — older inactive tickers ignored.
        last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
        for r in rows[1:]:
            if not r or len(r) < 2:
                continue
            if (r[0] or "")[:10] != last_date:
                continue
            t = (r[1] or "").strip().upper()
            if t and t.replace(".", "").isalnum():
                out.add(t)
    return out


# --- scanner POST -----------------------------------------------------------

@dataclass
class _BatchResult:
    rows: dict[str, dict]    # "EXCHANGE:TICKER" -> {col_name: value}
    missing: list[str]
    error: Optional[str]


def _scanner_post(symbols: list[str], logger: logging.Logger,
                  max_retries: int = 1) -> _BatchResult:
    """POST a batch of `EXCHANGE:TICKER` symbols. Returns daily close + change + volume."""
    body = {
        "symbols": {"tickers": symbols, "query": {"types": []}},
        "columns": TV_COLUMNS,
    }
    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                TV_ENDPOINT, json=body, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 casaa-tv-prices"},
            )
        except Exception as e:
            last_err = f"network: {e}"
            time.sleep(2)
            continue
        if r.status_code == 429:
            logger.warning(f"  TV 429 rate-limited, sleeping 60s")
            time.sleep(60)
            continue
        if r.status_code != 200:
            last_err = f"http {r.status_code}: {r.text[:150]}"
            time.sleep(2)
            continue
        try:
            payload = r.json()
        except Exception as e:
            last_err = f"json parse: {e}"
            time.sleep(2)
            continue
        rows = payload.get("data") or []
        out: dict[str, dict] = {}
        for row in rows:
            sym = row.get("s") or ""
            d = row.get("d") or []
            if not sym or len(d) < len(TV_COLUMNS):
                continue
            out[sym] = {col: d[i] for i, col in enumerate(TV_COLUMNS)}
        returned = set(out.keys())
        missing = [s for s in symbols if s not in returned]
        return _BatchResult(rows=out, missing=missing, error=None)
    return _BatchResult(rows={}, missing=symbols, error=last_err or "unknown")


# --- SGX fallback (yfinance) -------------------------------------------------

def _yahoo_sgx_prices(tickers: list[str], logger: logging.Logger) -> dict[str, dict]:
    """SGX tickers aren't on TV `america` — fall back to yfinance."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("  yfinance not available — SGX prices skipped")
        return {}
    import math
    out: dict[str, dict] = {}
    for t in tickers:
        try:
            yt = yf.Ticker(f"{t}.SI")
            hist = yt.history(period="2d", interval="1d")
            if len(hist) == 0:
                continue
            last = float(hist["Close"].iloc[-1])
            # yfinance occasionally returns NaN for thinly-traded SGX
            # tickers; skip those rather than poison the upsert.
            if math.isnan(last) or last <= 0:
                logger.warning(f"  {t}.SI returned NaN/0 — skipping")
                continue
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
            if math.isnan(prev) or prev <= 0:
                prev = last
            change_pct = ((last / prev) - 1) * 100 if prev else 0
            try:
                volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
            except (ValueError, TypeError):
                volume = 0
            out[t] = {
                "exchange": "SGX",
                "last": last,
                "change": change_pct,
                "volume": volume,
                "source": "yahoo",
            }
        except Exception as e:
            logger.warning(f"  {t}.SI yahoo fetch failed: {e}")
    return out


# --- upsert -----------------------------------------------------------------

def upsert_live_prices(client, rows_by_ticker: dict[str, dict],
                       logger: logging.Logger) -> int:
    """Upsert rows in the live_prices tab keyed by ticker."""
    sh.ensure_headers(client, S.LivePriceRow.TAB_NAME, S.LivePriceRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.LivePriceRow.TAB_NAME)
    existing = ws.get_all_values()

    # Map ticker → existing row index (1-based, header at row 1)
    existing_by_ticker: dict[str, int] = {}
    for i, r in enumerate(existing[1:], start=2):
        if r and len(r) > 0:
            existing_by_ticker[r[0]] = i

    # Build all rows (existing kept as-is unless ticker overlap)
    keep_rows: list[list[str]] = [existing[0] if existing else list(S.LivePriceRow.HEADERS)]
    for r in existing[1:]:
        if r and r[0] in rows_by_ticker:
            continue  # will be replaced below
        keep_rows.append(r)

    # Append fresh rows for upserted tickers (sorted for stability)
    now_sgt = S.now_sgt_iso()
    for ticker in sorted(rows_by_ticker.keys()):
        d = rows_by_ticker[ticker]
        row = S.LivePriceRow(
            ticker=ticker,
            exchange=str(d.get("exchange", "")),
            last=float(d.get("last", 0) or 0),
            change_pct=float(d.get("change", 0) or 0),
            volume=int(d.get("volume", 0) or 0),
            updated_at=now_sgt,
            source=str(d.get("source", "tv")),
        )
        keep_rows.append(row.to_row())

    # Single atomic bulk write — no clear() window that could leave the tab empty.
    sh.upsert_tab(ws, keep_rows)
    logger.info(f"✓ live_prices upserted: {len(rows_by_ticker)} tickers (kept {len(keep_rows)-1-len(rows_by_ticker)} unchanged)")
    return len(rows_by_ticker)


# --- main -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Parse + log only; no sheet write")
    args = p.parse_args()

    logger = setup_logging("tv-price-refresh")
    logger.info(f"tv_price_refresh start (dry={args.dry})")

    load_env()
    client = sh.authenticate()

    tickers = read_portfolio_tickers(client, logger)
    if not tickers:
        logger.warning("No portfolio tickers found — positions_* tabs empty?")
        return 0
    logger.info(f"  Portfolio universe: {len(tickers)} tickers")

    # Split US vs SGX
    sgx_tickers = sorted(t for t in tickers if t in SGX_TICKERS)
    us_tickers = sorted(t for t in tickers if t not in SGX_TICKERS)

    # Build EXCHANGE:TICKER symbols. Use known map; default to NASDAQ + probe later.
    us_symbols: list[str] = []
    sym_to_ticker: dict[str, str] = {}
    for t in us_tickers:
        ex = TICKER_EXCHANGE.get(t, "NASDAQ")
        sym = f"{ex}:{t}"
        us_symbols.append(sym)
        sym_to_ticker[sym] = t

    # First pass — try with primary exchange guess
    logger.info(f"  TV scanner POST: {len(us_symbols)} US tickers")
    result = _scanner_post(us_symbols, logger)
    if result.error:
        logger.warning(f"  TV first-pass error: {result.error}")

    # Probe missing tickers across other exchanges
    probe_attempts: list[str] = []
    if result.missing:
        miss_tickers = [sym_to_ticker[s] for s in result.missing if s in sym_to_ticker]
        for t in miss_tickers:
            primary = TICKER_EXCHANGE.get(t, "NASDAQ")
            for ex in EXCHANGE_PROBE_ORDER:
                if ex == primary:
                    continue
                probe_attempts.append(f"{ex}:{t}")
                sym_to_ticker[f"{ex}:{t}"] = t
        if probe_attempts:
            logger.info(f"  TV probe: {len(probe_attempts)} symbols across alt exchanges")
            probe_result = _scanner_post(probe_attempts, logger)
            for sym, d in probe_result.rows.items():
                result.rows[sym] = d

    # Translate scanner output back to ticker -> data map
    rows_by_ticker: dict[str, dict] = {}
    for sym, d in result.rows.items():
        t = sym_to_ticker.get(sym)
        if not t or t in rows_by_ticker:
            continue
        ex = sym.split(":", 1)[0] if ":" in sym else ""
        rows_by_ticker[t] = {
            "exchange": ex,
            "last": d.get("close", 0),
            "change": d.get("change", 0),
            "volume": d.get("volume", 0),
            "source": "tv",
        }

    # SGX fallback
    if sgx_tickers:
        logger.info(f"  Yahoo SGX fallback: {len(sgx_tickers)} tickers")
        sgx_data = _yahoo_sgx_prices(sgx_tickers, logger)
        rows_by_ticker.update(sgx_data)

    missing = sorted(set(tickers) - set(rows_by_ticker.keys()))
    logger.info(f"  Got prices for {len(rows_by_ticker)}/{len(tickers)} tickers")
    if missing:
        logger.warning(f"  Missing: {missing}")

    if args.dry:
        for t, d in sorted(rows_by_ticker.items()):
            logger.info(f"  [dry] {t:6} {d.get('exchange',''):6} last={d.get('last'):.4f}  chg%={d.get('change'):+.2f}  vol={d.get('volume')}")
        return 0

    upsert_live_prices(client, rows_by_ticker, logger)
    logger.info("tv_price_refresh done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
