"""
options_refresh_cloud.py — Cloud-friendly hourly refresh of derived fields on
KNOWN open option positions. Designed to run on GitHub Actions (no IBKR/TWS).

Architecture context (Tier 2 cloud migration, Apr 2026):
  Mac `ibkr-grab` LaunchAgent still owns NEW-position discovery (nightly,
  TWS-tethered) by writing PortfolioGrabs/YYYYMMDD_PortfolioGrab.json.
  Mac `daily-tracker` still does the JSON → initial `options` sheet rows.
  This cloud script keeps those rows FRESH between Mac runs by recomputing
  every yfinance-derivable field every 30 minutes during US market hours.

Cloud-derivable fields (recomputed every run):
  - underlying_last  : current stock price (yfinance Close)
  - last             : option mid price (yfinance option_chain bid/ask mid;
                       falls back to last_known if chain unavailable)
  - mkt_val          : qty × last × 100  (assuming 100-share multiplier)
  - upl              : mkt_val - (credit × qty × 100)  for shorts; sign flipped
                       for longs per IBKR convention
  - moneyness        : ITM/ATM/OTM from underlying vs strike
  - dte              : days to expiry from today
  - assignment_risk  : LOW/MED/HIGH from moneyness × dte × trend
  - momentum_5d      : 5-day %ROC from compute_indicators
  - trend_risk       : SAFE/DRIFTING/CONVERGING/BREACHING
  - volatility_annual: 60d realized σ × √252
  - rsi_14           : Wilder's 14-day RSI
  - sma_20, sma_50   : 20/50-day simple moving averages

Mac-tethered fields (preserved at last-known value):
  - credit              (avg_cost_credit / multiplier — set by IBKR)
  - wheel_leg           (depends on stock holdings — Mac builds the map)
  - adj_cost_basis      (depends on accumulated premiums — Mac state)
  - confidence_pct      (depends on full technical_scores — keep last)
  - confidence_reasoning (free-text, last-known wins)

Usage:
  python scripts/options_refresh_cloud.py            # live refresh
  python scripts/options_refresh_cloud.py --dry      # print, no sheet write

Idempotency:
  - If `options` tab is empty or has only header row → exit 0 cleanly.
  - If yfinance returns no data for a ticker → preserve last-known row, mark
    "no-data" in the log, still emit a fresh-timestamped row so the brain's
    latest_date filter advances.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# Reuse the same SGX list daily_tracker uses (Caspar's account holds these
# under their bare ticker; they need .SI suffix on Yahoo). yahoo_grab.py has a
# wider list — daily_tracker's is narrower because options are US-only.
SGX_TICKERS: set[str] = {"C6L", "G3B", "ES3"}

# Lookback window for per-position-latest selection. Positions whose most
# recent row is older than this are dropped (they're either closed-out or
# stale enough that we shouldn't resurrect them every refresh).
OPTIONS_LOOKBACK_DAYS: int = 7


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("options-refresh-cloud")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _yahoo_symbol(ticker: str) -> str:
    """Convert internal ticker → Yahoo Finance symbol."""
    return f"{ticker}.SI" if ticker in SGX_TICKERS else ticker


def _parse_expiry(expiry: str) -> date | None:
    """Accept 'YYYYMMDD' (IBKR format) or 'YYYY-MM-DD'."""
    s = (expiry or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fetch_indicators(tickers: list[str], logger: logging.Logger) -> dict[str, dict]:
    """
    Pull 1y OHLCV for each underlying and compute the indicator bundle.
    Reuses src.indicators (same path daily_tracker uses).
    """
    if not tickers:
        return {}
    from src.indicators import fetch_ohlcv, compute_indicators

    yahoo_syms = [_yahoo_symbol(t) for t in tickers]
    ohlcv = fetch_ohlcv(yahoo_syms, period="1y")
    out: dict[str, dict] = {}
    for orig, ysym in zip(tickers, yahoo_syms):
        df = ohlcv.get(ysym)
        if df is None or df.empty or len(df) < 20:
            logger.warning(f"  {orig}: insufficient OHLCV ({0 if df is None else len(df)} bars)")
            out[orig] = {}
            continue
        try:
            ind = compute_indicators(df)
            out[orig] = ind
        except Exception as e:
            logger.warning(f"  {orig}: indicator compute failed — {e}")
            out[orig] = {}
    return out


def _option_mid_from_chain(yahoo_sym: str, expiry_iso: str, right: str, strike: float, logger: logging.Logger) -> float | None:
    """
    Fetch option mid for a specific contract via yfinance option_chain.
    Returns None if chain unavailable, contract missing, or quote stale.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(yahoo_sym)
        chain = t.option_chain(expiry_iso)
    except Exception as e:
        logger.debug(f"    chain fetch failed for {yahoo_sym} {expiry_iso}: {e}")
        return None

    df = chain.puts if right == "P" else chain.calls
    if df is None or df.empty:
        return None

    # Find the matching strike (within 1c tolerance)
    for _, row in df.iterrows():
        try:
            K = float(row.get("strike", 0))
            if abs(K - strike) > 0.01:
                continue
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            last_p = float(row.get("lastPrice", 0) or 0)
            # Prefer live quote midpoint
            if bid > 0.01 and ask > 0.01:
                return (bid + ask) / 2
            # Fall back to last traded if it looks real
            if last_p > 0.01:
                return last_p
        except (ValueError, TypeError, KeyError):
            continue
    return None


def _calc_moneyness(right: str, strike: float, underlying: float) -> str:
    """ITM/ATM/OTM with 2% ATM band — same logic as daily_tracker."""
    if underlying <= 0 or strike <= 0:
        return "?"
    pct_diff = abs(underlying - strike) / strike
    if pct_diff < 0.02:
        return "ATM"
    if right == "C":
        return "ITM" if underlying > strike else "OTM"
    return "ITM" if underlying < strike else "OTM"


def _calc_dte(expiry: str) -> int:
    """Days to expiry from YYYYMMDD/YYYY-MM-DD. -1 if unparseable."""
    exp = _parse_expiry(expiry)
    return max(0, (exp - date.today()).days) if exp else -1


def _calc_trend_risk(right: str, strike: float, underlying: float, momentum_5d: float, is_short: bool) -> str:
    """Same logic as daily_tracker.calc_trend_risk — copied verbatim."""
    if underlying <= 0 or strike <= 0:
        return "?"
    dist_pct = (underlying - strike) / strike * 100

    if is_short:
        if right == "C":
            if dist_pct > 2 and momentum_5d > 1:
                return "BREACHING"
            elif dist_pct > -5 and momentum_5d > 1.5:
                return "CONVERGING"
            elif momentum_5d > 2 and dist_pct > -10:
                return "DRIFTING"
            return "SAFE"
        else:
            if dist_pct < -2 and momentum_5d < -1:
                return "BREACHING"
            elif dist_pct < 5 and momentum_5d < -1.5:
                return "CONVERGING"
            elif momentum_5d < -2 and dist_pct < 10:
                return "DRIFTING"
            return "SAFE"
    else:
        if right == "C":
            if dist_pct > 2 and momentum_5d > 0:
                return "SAFE"
            elif momentum_5d < -1.5:
                return "DRIFTING"
            return "SAFE"
        else:
            if dist_pct < -2 and momentum_5d < 0:
                return "SAFE"
            elif momentum_5d > 1.5:
                return "DRIFTING"
            return "SAFE"


def _latest_per_position(data: list[dict], lookback_days: int = OPTIONS_LOOKBACK_DAYS) -> list[dict]:
    """
    Select the most recent row for each unique open position
    (account, ticker, right, strike, expiry). Drops positions whose latest
    row is older than `lookback_days` so closed-out positions don't get
    resurrected forever.

    Replaces the older "latest_date = max(date)" timestamp-bucket logic, which
    failed when partial snapshots landed (e.g. yfinance hiccup on one account's
    tickers caused subsequent refreshes to inherit the gap forever — sarah's
    rows vanished from the options sheet for ~14 hours starting 2026-04-30
    22:14 UTC).
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    by_pos: dict[tuple, dict] = {}
    for row in data:
        key = (
            (row.get("account") or "").strip().lower(),
            (row.get("ticker")  or "").strip().upper(),
            (row.get("right")   or "").strip().upper(),
            (row.get("strike")  or "").strip(),
            (row.get("expiry")  or "").strip(),
        )
        if not key[1]:  # missing ticker — skip
            continue
        date_field = row.get("date") or ""
        # Drop rows older than cutoff (compare YYYY-MM-DD prefix)
        if date_field[:10] < cutoff:
            continue
        prev = by_pos.get(key)
        if prev is None or date_field > (prev.get("date") or ""):
            by_pos[key] = row
    return list(by_pos.values())


def _calc_assignment_risk(moneyness: str, dte: int, trend_risk: str = "") -> str:
    """Same logic as daily_tracker.calc_assignment_risk — copied verbatim."""
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
    return "LOW"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dry", action="store_true", help="Print, do not write to sheet")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== options-refresh-cloud start ===")

    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    # ─── Read latest options snapshot ───────────────────────────────────────
    ws = ss.worksheet("options")
    rows = ws.get_all_values()
    if len(rows) < 2:
        logger.info("Options tab is empty (no data rows) — nothing to refresh")
        logger.info("=== options-refresh-cloud done ===")
        return 0

    headers = rows[0]
    data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
    if not data:
        logger.info("Options tab has only blank rows — nothing to refresh")
        return 0

    latest_options = _latest_per_position(data)
    logger.info(
        f"Latest open positions: {len(latest_options)} "
        f"(per-position latest, {OPTIONS_LOOKBACK_DAYS} day lookback)"
    )

    # ─── Collect unique underlying tickers ──────────────────────────────────
    tickers = sorted({r["ticker"] for r in latest_options if r.get("ticker")})
    if not tickers:
        logger.warning("No tickers in latest snapshot — nothing to refresh")
        return 0
    logger.info(f"Underlyings to refresh: {', '.join(tickers)}")

    # ─── Fetch indicators (1y OHLCV → momentum/RSI/SMAs/sigma) ──────────────
    logger.info("Fetching indicators...")
    indicators = _fetch_indicators(tickers, logger)
    underlying_prices: dict[str, float] = {}
    for t in tickers:
        ind = indicators.get(t, {})
        if ind.get("close", 0) > 0:
            underlying_prices[t] = float(ind["close"])
    got = sum(1 for v in indicators.values() if v)
    logger.info(f"  Got indicators for {got}/{len(tickers)} tickers")
    for t, p in sorted(underlying_prices.items()):
        logger.info(f"  Price: {t:<6} = ${p:.2f}")

    # ─── Build refreshed rows ───────────────────────────────────────────────
    now_ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    refreshed_rows: list[list[str]] = []
    refreshed_count = 0
    skipped_count = 0
    chain_hits = 0
    chain_misses = 0

    for pos in latest_options:
        ticker = (pos.get("ticker") or "").strip()
        right  = (pos.get("right") or "").strip().upper()
        try:
            strike = float(pos.get("strike", 0) or 0)
            qty    = float(pos.get("qty", 0) or 0)
            credit = float(pos.get("credit", 0) or 0)
        except (ValueError, TypeError):
            logger.warning(f"  {ticker}: malformed numeric fields — preserving row as-is")
            skipped_count += 1
            new_row = [pos.get(h, "") for h in headers]
            if "date" in headers:
                new_row[headers.index("date")] = now_ts
            refreshed_rows.append(new_row)
            continue
        expiry = (pos.get("expiry") or "").strip()
        is_short = qty < 0

        # Underlying price + indicator bundle
        ind = indicators.get(ticker, {})
        underlying_last = underlying_prices.get(ticker, 0.0)
        if underlying_last <= 0:
            # Preserve last-known but timestamp-bump so latest_date advances
            logger.warning(f"  {ticker}: no underlying price — preserving last-known row")
            skipped_count += 1
            new_row = [pos.get(h, "") for h in headers]
            new_row[headers.index("date")] = now_ts
            refreshed_rows.append(new_row)
            continue

        # Indicators (with daily_tracker-compatible defaults)
        mom_5d   = float(ind.get("momentum_5d", 0.0))
        sigma    = float(ind.get("volatility_annual", 0.0))
        rsi_14   = float(ind.get("rsi_14", 50.0))
        sma_20   = float(ind.get("sma_20", 0.0))
        sma_50   = float(ind.get("sma_50", 0.0))

        # Recompute moneyness, DTE, trend, assignment_risk
        moneyness = _calc_moneyness(right, strike, underlying_last)
        dte = _calc_dte(expiry)
        trend = _calc_trend_risk(right, strike, underlying_last, mom_5d, is_short)
        assignment_risk = _calc_assignment_risk(moneyness, dte if dte >= 0 else 0, trend)

        # Try to refresh the option mid via chain. Yahoo expects ISO expiry.
        exp_dt = _parse_expiry(expiry)
        last_opt = float(pos.get("last", 0) or 0)  # fallback: last-known
        if exp_dt and right in ("P", "C") and strike > 0:
            yahoo_sym = _yahoo_symbol(ticker)
            iso_exp = exp_dt.strftime("%Y-%m-%d")
            mid = _option_mid_from_chain(yahoo_sym, iso_exp, right, strike, logger)
            if mid is not None and mid > 0:
                last_opt = mid
                chain_hits += 1
            else:
                chain_misses += 1
        else:
            chain_misses += 1

        # mkt_val and upl recompute (assume 100-share multiplier)
        # IBKR convention: shorts have qty < 0 and mkt_val negative (you owe).
        # upl = (credit_received - current_price) * |qty| * 100  for shorts;
        # For longs: upl = (current_price - cost) * qty * 100.
        mult = 100
        mkt_val = qty * last_opt * mult
        if is_short:
            # short: profit when option price drops below credit collected
            upl = (credit - last_opt) * abs(qty) * mult
        else:
            # long: profit when option price rises above premium paid
            # cost basis = credit field is paid premium for longs in IBKR feed
            upl = (last_opt - credit) * qty * mult

        # Build the refreshed row preserving original column order. Only
        # touch fields we own; preserve everything else from the source row.
        cloud_owned = {
            "date": now_ts,
            "underlying_last": f"{underlying_last:.4f}",
            "last": f"{last_opt:.4f}",
            "mkt_val": f"{mkt_val:.2f}",
            "upl": f"{upl:.2f}",
            "moneyness": moneyness,
            "dte": str(max(0, dte)) if dte >= 0 else "0",
            "assignment_risk": assignment_risk,
            "momentum_5d": f"{mom_5d:.2f}",
            "trend_risk": trend,
            "volatility_annual": f"{sigma:.4f}",
            "rsi_14": f"{rsi_14:.1f}",
            "sma_20": f"{sma_20:.2f}",
            "sma_50": f"{sma_50:.2f}",
        }
        new_row: list[str] = []
        for h in headers:
            if h in cloud_owned:
                new_row.append(cloud_owned[h])
            else:
                # Mac-tethered: credit, wheel_leg, adj_cost_basis,
                # confidence_pct, confidence_reasoning — keep last-known.
                new_row.append(pos.get(h, ""))
        refreshed_rows.append(new_row)
        refreshed_count += 1

        logger.info(
            f"  {ticker:<6} {right} ${strike:>7.2f} exp={expiry} dte={dte:>3} "
            f"u=${underlying_last:>7.2f} opt=${last_opt:>5.2f} "
            f"{moneyness:>3} risk={assignment_risk:<4} trend={trend:<10} "
            f"upl={upl:>+8.2f}"
        )

    # ─── Summary ────────────────────────────────────────────────────────────
    logger.info(
        f"Summary: {refreshed_count} refreshed | {skipped_count} preserved | "
        f"chain_hits={chain_hits} chain_misses={chain_misses}"
    )

    if args.dry:
        logger.info(f"[DRY] Would append {len(refreshed_rows)} rows to options")
        logger.info("=== options-refresh-cloud done ===")
        return 0

    if not refreshed_rows:
        logger.info("No rows to write")
        return 0

    ws.append_rows(refreshed_rows, value_input_option="USER_ENTERED")
    logger.info(f"OK Appended {len(refreshed_rows)} refreshed option rows to `options`")
    logger.info("=== options-refresh-cloud done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
