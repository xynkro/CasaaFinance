"""
finnhub_calendars.py — daily Finnhub pull for earnings + economic calendars.

Two outputs in one script (single API auth, single sheet client):

1. earnings_calendar — per-ticker earnings dates for the next 30 days,
   filtered to portfolio + watchlist tickers (so we don't store the
   entire S&P 500 calendar). Brain reads this for "today's earnings"
   in Daily Brief and "DTE-inside earnings" warnings in WSR.

2. economic_calendar — macro releases (CPI/NFP/FOMC/GDP) for next 14
   days, filtered to US + EU + CN + JP only (other countries are noise
   for our portfolio). Brain reads this for "today's macro events" in
   Daily Brief and "macro week-ahead" in WSR Full.

Both UPSERT semantics — same (ticker, quarter) or (date, event) collapses
to one row, so re-pulls overwrite stale forecasts with actuals as they
land post-release.

Why Finnhub
-----------
- Earnings calendar with EPS estimates + actuals + surprise%
- Economic calendar with importance flag (we filter for medium+high only)
- Free tier: 60 req/min; this script does ~30 req per run.
- Already used elsewhere wouldn't be true — this is the first Finnhub
  consumer in the codebase. Adds FINNHUB_API_KEY to GH secrets.

Usage
-----
  python scripts/finnhub_calendars.py            # live — upserts both tabs
  python scripts/finnhub_calendars.py --dry      # parse + log only

Schedule
--------
GitHub Actions cron: daily 13:00 UTC (≈21:00 SGT). Single daily refresh
is enough — calendars rarely shift intra-day. See
`.github/workflows/finnhub-calendars.yml`.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402

FH_BASE = "https://finnhub.io/api/v1"

# How far ahead we pull. Earnings tend to be scheduled 4-8 weeks out;
# macro releases ~2-4 weeks. Going wider just bloats the sheet.
EARNINGS_LOOKAHEAD_DAYS = 30
ECONOMIC_LOOKAHEAD_DAYS = 14

# Countries we care about (filter out the long tail of micro-events).
ECONOMIC_COUNTRY_WHITELIST = {"US", "EU", "CN", "JP", "GB", "DE", "SG"}

# Finnhub returns `impact` as a string ("low"/"medium"/"high"). Map to
# numeric for filtering, then store the canonical string back. Brain
# flags "high" in the Daily Brief.
IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}
IMPACT_KEEP_MIN = 1  # medium+


def _fh_get(path: str, params: dict, logger: logging.Logger,
            retries: int = 2) -> dict | list | None:
    """GET wrapper with auth + retry on 429/5xx."""
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    params = {**params, "token": api_key}
    url = f"{FH_BASE}/{path}"
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=15)
        except Exception as e:
            logger.warning(f"  {path} network error: {e} (attempt {attempt+1})")
            time.sleep(2)
            continue
        if r.status_code == 429:
            logger.warning(f"  {path} rate-limited; sleeping 30s")
            time.sleep(30)
            continue
        if r.status_code != 200:
            logger.warning(f"  {path} http {r.status_code}: {r.text[:150]}")
            time.sleep(2)
            continue
        try:
            return r.json()
        except Exception as e:
            logger.warning(f"  {path} json parse: {e}")
            return None
    logger.error(f"  {path} failed after {retries+1} attempts")
    return None


# --- universe ---------------------------------------------------------------

def read_portfolio_tickers(client, logger: logging.Logger) -> set[str]:
    """Latest-day portfolio tickers from positions_caspar + positions_sarah."""
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


def read_watchlist_tickers(client, logger: logging.Logger) -> set[str]:
    """Watchlist universe from prompts/watchlist.yaml (curated brain universe)."""
    try:
        from src.watchlist import get_universe
        u = get_universe(client)
        return set(t for ts in u.values() for t in ts)
    except Exception as e:
        logger.warning(f"  [universe] watchlist read failed: {e}")
        return set()


# --- earnings ---------------------------------------------------------------

def pull_earnings(tickers: set[str], logger: logging.Logger) -> list[S.EarningsRow]:
    """Pull earnings for next EARNINGS_LOOKAHEAD_DAYS, filtered to our universe."""
    today = datetime.utcnow().date()
    end = today + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)
    payload = _fh_get(
        "calendar/earnings",
        {"from": today.isoformat(), "to": end.isoformat()},
        logger,
    )
    if not payload:
        return []
    cal = payload.get("earningsCalendar") or []
    logger.info(f"  earnings: {len(cal)} entries (next {EARNINGS_LOOKAHEAD_DAYS} days, all symbols)")

    # Filter to our universe
    rows: list[S.EarningsRow] = []
    now_sgt = S.now_sgt_iso()
    for e in cal:
        sym = (e.get("symbol") or "").upper()
        if sym not in tickers:
            continue
        eps_est = e.get("epsEstimate")
        eps_act = e.get("epsActual")
        rev_est = e.get("revenueEstimate")
        rev_act = e.get("revenueActual")
        # Surprise % = (actual - estimate) / abs(estimate) × 100
        surprise = None
        if eps_act is not None and eps_est not in (None, 0):
            try:
                surprise = (float(eps_act) - float(eps_est)) / abs(float(eps_est)) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                surprise = None
        rows.append(S.EarningsRow(
            date=str(e.get("date") or ""),
            ticker=sym,
            hour=str(e.get("hour") or ""),
            year=int(e.get("year") or 0),
            quarter=int(e.get("quarter") or 0),
            eps_estimate=eps_est,
            eps_actual=eps_act,
            revenue_estimate=rev_est,
            revenue_actual=rev_act,
            surprise_pct=surprise,
            updated_at=now_sgt,
        ))
    logger.info(f"  earnings filtered to portfolio+watchlist: {len(rows)} rows")
    return rows


def upsert_earnings(client, rows: list[S.EarningsRow], logger: logging.Logger) -> int:
    """UPSERT keyed by (ticker, year, quarter)."""
    sh.ensure_headers(client, S.EarningsRow.TAB_NAME, S.EarningsRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.EarningsRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.EarningsRow.HEADERS)

    new_keys = {(r.ticker, r.year, r.quarter) for r in rows}
    keep: list[list[str]] = [hdr]
    dropped = 0
    for r in existing[1:]:
        if not r or len(r) < 5:
            continue
        try:
            key = (r[1], int(r[3] or 0), int(r[4] or 0))
        except ValueError:
            keep.append(r)
            continue
        if key in new_keys:
            dropped += 1
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(f"✓ earnings upserted: {len(rows)} (dropped {dropped} stale)")
    return len(rows)


# --- economic ---------------------------------------------------------------

def pull_economic(logger: logging.Logger) -> list[S.EconomicEventRow]:
    """Pull economic calendar — medium+high impact only, US/EU/CN/JP/etc."""
    today = datetime.utcnow().date()
    end = today + timedelta(days=ECONOMIC_LOOKAHEAD_DAYS)
    payload = _fh_get(
        "calendar/economic",
        {"from": today.isoformat(), "to": end.isoformat()},
        logger,
    )
    if not payload:
        return []
    cal = payload.get("economicCalendar") or []
    logger.info(f"  economic: {len(cal)} entries (raw)")

    rows: list[S.EconomicEventRow] = []
    now_sgt = S.now_sgt_iso()
    for e in cal:
        country = (e.get("country") or "").upper()
        if country not in ECONOMIC_COUNTRY_WHITELIST:
            continue
        impact_str = str(e.get("impact") or "low").lower()
        impact_rank = IMPACT_RANK.get(impact_str, 0)
        if impact_rank < IMPACT_KEEP_MIN:
            continue
        # Finnhub returns "time" as ISO datetime "YYYY-MM-DD HH:MM:SS"
        ts_full = str(e.get("time") or "")
        if " " in ts_full:
            d, t = ts_full.split(" ", 1)
            t = t[:5]  # HH:MM
        else:
            d = ts_full[:10]
            t = ""
        rows.append(S.EconomicEventRow(
            date=d,
            time=t,
            country=country,
            event=str(e.get("event") or ""),
            impact=impact_str,
            forecast=str(e.get("estimate") or ""),
            actual=str(e.get("actual") or ""),
            previous=str(e.get("prev") or ""),
            unit=str(e.get("unit") or ""),
            updated_at=now_sgt,
        ))
    logger.info(f"  economic filtered (medium+high, our countries): {len(rows)} rows")
    return rows


def upsert_economic(client, rows: list[S.EconomicEventRow], logger: logging.Logger) -> int:
    """UPSERT keyed by (date, time, country, event)."""
    sh.ensure_headers(client, S.EconomicEventRow.TAB_NAME, S.EconomicEventRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.EconomicEventRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.EconomicEventRow.HEADERS)

    new_keys = {(r.date, r.time, r.country, r.event) for r in rows}
    keep: list[list[str]] = [hdr]
    dropped = 0
    for r in existing[1:]:
        if not r or len(r) < 4:
            continue
        key = (r[0], r[1], r[2], r[3])
        if key in new_keys:
            dropped += 1
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(f"✓ economic upserted: {len(rows)} (dropped {dropped} stale)")
    return len(rows)


# --- main -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Parse + log only; no sheet write")
    args = p.parse_args()

    logger = setup_logging("finnhub-calendars")
    logger.info(f"finnhub_calendars start (dry={args.dry})")

    load_env()
    client = sh.authenticate()

    portfolio = read_portfolio_tickers(client, logger)
    watchlist = read_watchlist_tickers(client, logger)
    universe = portfolio | watchlist
    logger.info(f"  Universe: {len(portfolio)} portfolio + {len(watchlist)} watchlist = {len(universe)} unique")

    earnings_rows = pull_earnings(universe, logger)
    economic_rows = pull_economic(logger)

    if args.dry:
        logger.info("--- earnings preview ---")
        for r in earnings_rows[:8]:
            logger.info(
                f"  {r.date} {r.ticker:6} {r.hour:3} Q{r.quarter} "
                f"eps_est={r.eps_estimate}  eps_act={r.eps_actual}  surprise%={r.surprise_pct}"
            )
        if len(earnings_rows) > 8:
            logger.info(f"  ... and {len(earnings_rows)-8} more")
        logger.info("--- economic preview ---")
        for r in economic_rows[:8]:
            logger.info(
                f"  {r.date} {r.time} {r.country} {r.impact:6} {r.event[:60]}"
            )
        if len(economic_rows) > 8:
            logger.info(f"  ... and {len(economic_rows)-8} more")
        return 0

    if earnings_rows:
        upsert_earnings(client, earnings_rows, logger)
    if economic_rows:
        upsert_economic(client, economic_rows, logger)

    logger.info("finnhub_calendars done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
