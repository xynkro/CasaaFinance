"""
iv_surface_scan.py — IV Surface Option Scanner

Fetches multi-expiry option chains for portfolio tickers, fits a 2D
polynomial IV surface via OLS, and scores contracts by IV excess
(actual minus fitted) to surface mispriced premium.

Pipeline:
  1. Gather universe from Sheet (positions_caspar + positions_sarah + harvest_scan)
  2. Fetch multi-expiry chains from yfinance (14-120 DTE)
  3. Fit IV surface per ticker: log_moneyness × sqrt_time polynomial
  4. Score each contract (IV excess, annualised yield, delta, assignment risk)
  5. Write scored rows to Sheet tab: iv_surface_scan

Triggered daily by GitHub Actions at 13:00 UTC (8am ET).

Usage:
  python scripts/iv_surface_scan.py                       # full live scan
  python scripts/iv_surface_scan.py --dry                 # print, no sheet write
  python scripts/iv_surface_scan.py --dry --tickers AVGO  # single ticker dry run
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.bsm import norm_cdf  # noqa: E402
from src.logging_util import setup_logging  # noqa: E402


# ─── Parameters ───────────────────────────────────────────────────────────────
MIN_DTE = 14
MAX_DTE = 120
MIN_FIT_ROWS = 5       # minimum contracts to attempt surface fit
RATE_LIMIT_S = 0.5     # sleep between tickers


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Universe
# ═══════════════════════════════════════════════════════════════════════════════

def _gather_universe(client, logger) -> list[str]:
    """Read tickers from positions_caspar, positions_sarah, harvest_scan. Deduplicate."""
    from src import sheets as sh

    tickers: set[str] = set()
    ss = sh._open_sheet(client)

    # positions_caspar + positions_sarah: ticker is column index 1
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            rows = ss.worksheet(tab).get_all_values()
        except Exception as e:
            logger.warning(f"  [universe] {tab} read failed: {e}")
            continue
        if len(rows) <= 1:
            continue
        last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
        for r in rows[1:]:
            if not r or len(r) < 2:
                continue
            if (r[0] or "")[:10] != last_date:
                continue
            t = (r[1] or "").strip().upper()
            if t and t.replace(".", "").isalnum():
                tickers.add(t)

    # harvest_scan: ticker is column index 1
    try:
        rows = ss.worksheet("harvest_scan").get_all_values()
        if len(rows) > 1:
            last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
            for r in rows[1:]:
                if not r or len(r) < 2:
                    continue
                if (r[0] or "")[:10] != last_date:
                    continue
                t = (r[1] or "").strip().upper()
                if t and t != "--" and t.replace(".", "").isalnum():
                    tickers.add(t)
    except Exception as e:
        logger.warning(f"  [universe] harvest_scan read failed: {e}")

    result = sorted(tickers)
    logger.info(f"Universe: {len(result)} tickers from Sheet")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Chain fetch
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_chains(ticker: str, min_dte: int = MIN_DTE, max_dte: int = MAX_DTE,
                  logger=None) -> list[dict]:
    """
    Fetch multi-expiry option chains from yfinance.
    Returns list of dicts with keys:
      type, strike, expiry, dte, spot, iv, bid, ask, mid, oi, volume
    Skips contracts with iv=0 or bid=0.
    """
    import yfinance as yf

    contracts: list[dict] = []
    try:
        yt = yf.Ticker(ticker)
        expiries = yt.options
    except Exception as e:
        if logger:
            logger.warning(f"  {ticker}: options fetch failed — {e}")
        return []

    if not expiries:
        return []

    # Get spot price
    try:
        hist = yt.history(period="5d", auto_adjust=True)
        if hist.empty:
            return []
        spot = float(hist["Close"].dropna().iloc[-1])
    except Exception:
        return []

    today = date.today()

    for exp_str in expiries:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp_date - today).days
        if dte < min_dte or dte > max_dte:
            continue

        try:
            chain = yt.option_chain(exp_str)
        except Exception:
            continue

        for side, df in [("P", chain.puts), ("C", chain.calls)]:
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                raw_iv = row.get("impliedVolatility", 0)
                iv = float(raw_iv) if raw_iv is not None and not (isinstance(raw_iv, float) and math.isnan(raw_iv)) else 0.0
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                if iv < 0.001 or bid <= 0:
                    continue
                strike_f = float(row["strike"])
                # SELLABLE-ZONE filter — this is a premium-SELLING surface.
                # (a) OTM-only (5% ITM grace for ATM continuity): deep-ITM rows
                #     are all intrinsic, the IV solve explodes (100-600% "IV"),
                #     and they were polluting the surface FIT — which corrupted
                #     iv_fitted/iv_excess for every real candidate downstream.
                # (b) Moneyness window ±45%: nobody wheels a strike half the
                #     spot away; dropping the far tails cut the tab from ~14.5k
                #     rows (a ~5MB / 6-doc mobile payload) to a sane size.
                if side == "P" and strike_f > spot * 1.05:
                    continue
                if side == "C" and strike_f < spot * 0.95:
                    continue
                if not (spot * 0.55 <= strike_f <= spot * 1.45):
                    continue
                mid = (bid + ask) / 2.0
                # oi/volume can be NaN in yfinance
                raw_oi = row.get("openInterest", 0)
                raw_vol = row.get("volume", 0)
                oi = int(raw_oi) if raw_oi is not None and not (isinstance(raw_oi, float) and math.isnan(raw_oi)) else 0
                vol = int(raw_vol) if raw_vol is not None and not (isinstance(raw_vol, float) and math.isnan(raw_vol)) else 0

                contracts.append({
                    "type": side,
                    "strike": float(row["strike"]),
                    "expiry": exp_str,
                    "dte": dte,
                    "spot": spot,
                    "iv": iv,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "oi": oi,
                    "volume": vol,
                })
    return contracts


# ═══════════════════════════════════════════════════════════════════════════════
# 3. IV Surface fit
# ═══════════════════════════════════════════════════════════════════════════════

def _fit_iv_surface(contracts: list[dict]) -> list[float] | None:
    """
    Fit 2D polynomial IV surface via OLS.

    Design matrix: [1, m, m², sqrt_t, m*sqrt_t]
    where m = ln(strike/spot), sqrt_t = sqrt(dte/365).

    Returns fitted IV per contract (same length as input), or None if < 5 rows.
    """
    if len(contracts) < MIN_FIT_ROWS:
        return None

    n = len(contracts)
    y = np.array([c["iv"] for c in contracts])
    m = np.array([math.log(c["strike"] / c["spot"]) for c in contracts])
    sqrt_t = np.array([math.sqrt(c["dte"] / 365.0) for c in contracts])

    # Design matrix: [1, m, m², √t, m·√t]
    X = np.column_stack([
        np.ones(n),
        m,
        m ** 2,
        sqrt_t,
        m * sqrt_t,
    ])

    try:
        coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        iv_fitted = X @ coeffs
        return iv_fitted.tolist()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Black-Scholes delta
# ═══════════════════════════════════════════════════════════════════════════════

def _bs_delta(spot: float, strike: float, iv: float, dte: int,
              r: float = 0.045, option_type: str = "P") -> float:
    """
    Black-Scholes delta.
    Puts: N(d1) - 1.  Calls: N(d1).
    """
    T = dte / 365.0
    if T <= 0 or iv <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
    if option_type == "C":
        return norm_cdf(d1)
    else:
        return norm_cdf(d1) - 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Earnings date
# ═══════════════════════════════════════════════════════════════════════════════

def _get_earnings_date(ticker: str) -> date | None:
    """Get next earnings date from yfinance. Returns date or None."""
    import yfinance as yf

    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return None
        # yfinance returns calendar as a dict with 'Earnings Date' key
        # that may be a list of Timestamps or a single Timestamp
        ed = cal.get("Earnings Date") or cal.get("earningsDate")
        if ed is None:
            return None
        if isinstance(ed, list):
            if not ed:
                return None
            ed = ed[0]
        # Could be a Timestamp or datetime
        if hasattr(ed, "date"):
            return ed.date()
        if isinstance(ed, str):
            return datetime.strptime(ed[:10], "%Y-%m-%d").date()
        return None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Scoring
# ═══════════════════════════════════════════════════════════════════════════════

def _score_row(contract: dict, iv_fitted: float, ticker: str, spot: float,
               earnings_date: date | None) -> Any:
    """Build an IvSurfaceScanRow from a contract + fitted IV."""
    from src.schema import IvSurfaceScanRow as Row

    iv = contract["iv"]
    iv_excess = (iv - iv_fitted) * 100  # percentage points

    mid = contract["mid"]
    strike = contract["strike"]
    dte = contract["dte"]
    bid = contract["bid"]
    ask = contract["ask"]
    option_type = contract["type"]

    # Annualised yield
    if dte > 0 and mid > 0:
        if option_type == "P":
            ann_yield_pct = (mid / strike) * (365 / dte) * 100
        else:
            ann_yield_pct = (mid / spot) * (365 / dte) * 100
    else:
        ann_yield_pct = 0.0

    # Spread
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0.0

    # Delta
    delta = _bs_delta(spot, strike, iv, dte, option_type=option_type)

    # Assignment risk
    abs_delta = abs(delta)
    if abs_delta < 0.15:
        assignment_risk = "LOW"
    elif abs_delta <= 0.30:
        assignment_risk = "MEDIUM"
    else:
        assignment_risk = "HIGH"

    # Earnings before expiry
    expiry_date = datetime.strptime(contract["expiry"], "%Y-%m-%d").date()
    earnings_before = (earnings_date is not None and earnings_date < expiry_date)

    return Row(
        date=date.today().isoformat(),
        ticker=ticker,
        type=option_type,
        strike=strike,
        expiry=contract["expiry"],
        dte=dte,
        spot=spot,
        iv=iv,
        iv_fitted=iv_fitted,
        iv_excess=round(iv_excess, 2),
        delta=round(delta, 4),
        bid=bid,
        ask=ask,
        mid=mid,
        ann_yield_pct=round(ann_yield_pct, 1),
        oi=contract["oi"],
        volume=contract["volume"],
        spread_pct=round(spread_pct, 1),
        assignment_risk=assignment_risk,
        earnings_before_expiry=earnings_before,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="IV Surface Option Scanner")
    ap.add_argument("--dry", action="store_true", help="Print only, no sheet write")
    ap.add_argument("--tickers", nargs="+", help="Override universe with specific tickers")
    args = ap.parse_args()

    logger = setup_logging("iv-surface-scan")
    logger.info("═══ IV Surface Scanner ═══")

    # ── Universe ──
    if args.tickers:
        universe = [t.upper() for t in args.tickers]
        logger.info(f"Universe: {len(universe)} tickers from CLI override")
    else:
        from src.sync import load_env
        load_env()
        from src import sheets as sh
        client = sh.authenticate()
        universe = _gather_universe(client, logger)
        if not universe:
            logger.error("Empty universe — aborting")
            return 1

    # ── Scan loop ──
    from src.schema import IvSurfaceScanRow as Row
    all_rows: list[Row] = []

    for i, ticker in enumerate(universe):
        try:
            logger.info(f"  [{i + 1}/{len(universe)}] {ticker}")

            # Fetch chains
            contracts = _fetch_chains(ticker, logger=logger)
            if not contracts:
                logger.info(f"    {ticker}: no valid contracts in {MIN_DTE}-{MAX_DTE} DTE range")
                continue

            spot = contracts[0]["spot"]
            logger.info(f"    {ticker}: {len(contracts)} contracts, spot=${spot:.2f}")

            # Fit IV surface
            fitted = _fit_iv_surface(contracts)
            if fitted is None:
                logger.info(f"    {ticker}: < {MIN_FIT_ROWS} contracts, skipping surface fit")
                continue

            # Earnings date (one call per ticker)
            earnings_date = _get_earnings_date(ticker)

            # Score each contract
            for j, contract in enumerate(contracts):
                row = _score_row(contract, fitted[j], ticker, spot, earnings_date)
                all_rows.append(row)

            logger.info(f"    {ticker}: scored {len(contracts)} contracts (earnings={'yes' if earnings_date else 'no'})")

        except Exception as e:
            logger.warning(f"    {ticker}: error — {e}")

        # Rate limit
        if i < len(universe) - 1:
            time.sleep(RATE_LIMIT_S)

    logger.info(f"Total: {len(all_rows)} scored contracts across {len(universe)} tickers")

    # ── Sort by IV excess descending (richest premium first) ──
    all_rows.sort(key=lambda r: r.iv_excess, reverse=True)

    # ── Print top rows ──
    for r in all_rows[:15]:
        logger.info(
            f"  {r.ticker:6} {r.type} ${r.strike:>8.2f} {r.expiry} "
            f"iv={r.iv:.3f} fit={r.iv_fitted:.3f} excess={r.iv_excess:+.1f}pp "
            f"yld={r.ann_yield_pct:.0f}% d={r.delta:.3f} {r.assignment_risk}"
        )

    if args.dry:
        logger.info("DRY RUN — no sheet write")
        return 0

    # ── Write to Sheet ──
    try:
        from src.sync import load_env
        from src import sheets as sh
        load_env()
        client = sh.authenticate()

        # Fresh scan each day — ATOMIC full-tab overwrite. The old
        # delete_rows()+append_rows() pair left the tab observably EMPTY between
        # the two calls (a crash/429 in that window wiped the surface until the
        # next run). upsert_tab writes header+rows and blanks any stale tail in
        # ONE call.
        ws = sh.ensure_headers(client, Row.TAB_NAME, Row.HEADERS)
        sh.upsert_tab(ws, [Row.HEADERS] + [r.to_row() for r in all_rows])
        logger.info(f"  Wrote {len(all_rows)} rows to {Row.TAB_NAME}")
    except Exception as e:
        logger.error(f"  Sheet write failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
