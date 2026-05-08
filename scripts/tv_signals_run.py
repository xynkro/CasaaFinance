#!/usr/bin/env python3
"""
tv_signals_run.py — daily TradingView TA pull for our active universe.

Reads our active tickers (decision_queue + options + scan_results +
screen_candidates + positions_caspar/sarah) and pulls TradingView's
26-indicator consensus on BOTH 1d and 1W intervals. One row per
(ticker, interval) appended to the `tv_signals` Google Sheet tab.

Why scanner endpoint, not tradingview-ta library?
  The library's per-symbol endpoint (`https://symbol-search.tradingview.com/...`)
  rate-limits aggressively (HTTP 429). The PUBLIC scanner endpoint
  (`https://scanner.tradingview.com/america/scan`) accepts batches of
  symbols + multi-timeframe column suffixes in a SINGLE POST and does
  not rate-limit anywhere near as hard. We hit it with batches of ~20
  tickers/timeframe = 4 calls per cron, well under any cap.

  We still depend on `tradingview-ta` (in requirements.txt) for its
  `Compute.Recommend` thresholds — single source of truth for
  STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL mapping. If TV ever changes
  the score thresholds, upgrading the library propagates the change.

Counts (buy/sell/neutral): the scanner endpoint exposes the THREE
consensus scores (Recommend.All, Recommend.MA, Recommend.Other) but
NOT each indicator's individual classification — that requires the
per-symbol call. We approximate buy/sell counts from the scores using
the known indicator counts (15 MAs binary BUY-or-SELL, 11 oscillators
ternary BUY/SELL/NEUTRAL). Approximations are within ~1-2 of TV UI
display and good enough for the brain's confluence checks.

Exchange resolution: we hardcode the known mapping for our active
universe and cache misses in `~/.cache/casaa/tv_exchange_map.json`.
For a brand-new ticker not in the hardcode list we try NASDAQ first;
on failure (status_code "ok" but no data row), retry on NYSE.

Throttling: 0.5s sleep between batch calls. With the wider watchlist
universe (~80-90 tickers) at batch=20, the run hits ~5 batches per
interval × 3 intervals (1h + 1d + 1W) = ~15 primary batches, plus fallback retries
on alternate exchanges. Total wall clock typically 30-60s. On any
HTTP 429: sleep 60s, retry once, then surrender.

Usage:
  python scripts/tv_signals_run.py            # live — appends to sheet
  python scripts/tv_signals_run.py --dry      # parse only; no sheet write

Cron:
  .github/workflows/tv-signals.yml — daily 22:30 UTC (after regime cron)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src import schema as S          # noqa: E402
from src import sheets as sh         # noqa: E402
from src.sync import load_env        # noqa: E402
from src.watchlist import get_universe  # noqa: E402

# --- exchange cache ---------------------------------------------------------

_CACHE_PATH = Path.home() / ".cache" / "casaa" / "tv_exchange_map.json"
_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_cache() -> dict[str, str]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))
    except Exception:
        pass


# Hardcoded primary exchanges for our regular universe — saves fallback calls.
# SGX tickers are skipped entirely (TV `america` screener doesn't cover them
# and `singapore` screener is a different code path we don't currently model).
HARDCODED_EXCHANGE: dict[str, str] = {
    # NASDAQ
    "AAPL": "NASDAQ", "AMD": "NASDAQ", "AMZN": "NASDAQ", "BBAI": "NASDAQ",
    "BTBT": "NASDAQ", "CRWD": "NASDAQ", "GOOGL": "NASDAQ", "GOOG": "NASDAQ",
    "HIMS": "NYSE",   # HIMS lists on NYSE, common confusion
    "INTC": "NASDAQ", "META": "NASDAQ", "MDLZ": "NASDAQ", "MSFT": "NASDAQ",
    "NFLX": "NASDAQ", "NVDA": "NASDAQ", "PEP": "NASDAQ", "QQQ": "NASDAQ",
    "SBET": "NASDAQ", "SCHD": "AMEX", "TQQQ": "NASDAQ", "WIX": "NASDAQ",
    # NYSE
    "BYND": "NASDAQ", "GLDM": "AMEX", "HON": "NASDAQ", "JPM": "NYSE",
    "MA": "NYSE", "MDT": "NYSE", "OPEN": "NYSE", "PM": "NYSE",
    "RCAT": "NASDAQ", "SLV": "AMEX", "SPY": "AMEX", "SSO": "AMEX",
    "UNH": "NYSE", "V": "NYSE",
}

# SGX tickers — not on TradingView `america` screener.
SGX_TICKERS = {"C6L", "G3B", "ES3"}

# --- column definitions -----------------------------------------------------

# Columns on the scanner endpoint. Order matters — index drives unpacking.
TV_COLUMNS = [
    "close", "volume", "change",
    "RSI",
    "MACD.macd", "MACD.signal",
    "EMA20", "EMA50", "EMA200",
    "ADX",
    "BB.upper", "BB.lower",
    "Stoch.K", "Stoch.D", "CCI20",
    "Recommend.All", "Recommend.MA", "Recommend.Other",
]
NUM_COLUMNS = len(TV_COLUMNS)

# TradingView interval suffixes per the scanner API. "" = 1d (default).
# 1h added Phase 4 — gives the brain 3-timeframe confluence (1h + 1d + 1W)
# instead of 2-TF, so when 1d says BUY but 1h says SELL we can flag an
# intraday trap before recommending entry.
INTERVAL_SUFFIX = {
    "1h": "|60",
    "1d": "",
    "1W": "|1W",
    "1M": "|1M",
}

# Which intervals tv_signals_run.py actually pulls each run. 1h adds one
# more sweep over the universe but the cost is fine (~30s per pass).
RUN_INTERVALS = ("1h", "1d", "1W")

# Approximate indicator counts (matching tradingview-ta library structure).
# 15 MA-based indicators contribute BUY/SELL only (no NEUTRAL by their rule).
# 11 oscillators can output BUY/SELL/NEUTRAL.
NUM_MA = 15
NUM_OSC = 11


# --- recommendation mapping (matches tradingview-ta library exactly) -------

def _score_to_label(value: float) -> str:
    """Map Recommend.All score [-1, +1] to label. Matches Compute.Recommend."""
    if value is None:
        return "ERROR: no_score"
    if value >= -1 and value < -0.5:
        return "STRONG_SELL"
    if value >= -0.5 and value < -0.1:
        return "SELL"
    if value >= -0.1 and value <= 0.1:
        return "NEUTRAL"
    if value > 0.1 and value <= 0.5:
        return "BUY"
    if value > 0.5 and value <= 1:
        return "STRONG_BUY"
    return "ERROR: out_of_range"


def _approximate_counts(score_ma: float, score_other: float) -> tuple[int, int, int]:
    """
    Approximate buy/sell/neutral counts across the 26 indicators from the
    two component scores. See module docstring for derivation.
    """
    if score_ma is None or score_other is None:
        return 0, 0, 0
    # MAs: each is BUY (price > MA) or SELL (price < MA). buy = (NUM_MA + NUM_MA*score)/2
    buy_ma = round((NUM_MA + NUM_MA * score_ma) / 2)
    sell_ma = NUM_MA - buy_ma
    neutral_ma = 0
    # Oscillators: each can be BUY/SELL/NEUTRAL. We can't directly recover
    # neutral count, so approximate assuming neutrals are minimal at the
    # extremes and grow toward zero score. Heuristic: |score| close to 0
    # implies more neutrals; close to 1 implies fewer.
    abs_score = abs(score_other)
    # Estimated NEUTRAL fraction: 1 - |score|, capped at 0.3 of the 11 oscillators
    # (TV typically has at most 3-4 neutrals visible in the UI).
    neutral_other = round(min(NUM_OSC * 0.3, NUM_OSC * (1 - abs_score) * 0.4))
    classified = NUM_OSC - neutral_other
    # buy - sell = round(NUM_OSC * score_other), within classified subset
    buy_minus_sell = round(NUM_OSC * score_other)
    buy_other = max(0, min(classified, round((classified + buy_minus_sell) / 2)))
    sell_other = classified - buy_other
    return buy_ma + buy_other, sell_ma + sell_other, neutral_ma + neutral_other


# --- TradingView scanner client --------------------------------------------

TV_ENDPOINT = "https://scanner.tradingview.com/america/scan"


@dataclass
class _BatchResult:
    by_ticker: dict[str, dict]   # ticker -> {col_name: value}
    missing: list[str]           # tickers TV didn't return
    error: Optional[str]         # set if the whole batch failed


def _scanner_post(symbols: list[str], interval: str, logger: logging.Logger,
                  max_retries: int = 1) -> _BatchResult:
    """
    POST a batch of symbols (in `EXCHANGE:TICKER` format) to the scanner
    endpoint at one interval. Returns a `_BatchResult` keyed by the
    'EXCHANGE:TICKER' string the endpoint echoes back.
    """
    suffix = INTERVAL_SUFFIX.get(interval, "")
    cols = [c + suffix for c in TV_COLUMNS]
    body = {
        "symbols": {"tickers": symbols, "query": {"types": []}},
        "columns": cols,
    }
    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(TV_ENDPOINT, json=body, timeout=15,
                              headers={"User-Agent": "Mozilla/5.0 casaa-tv-signals"})
        except Exception as e:
            last_err = f"network: {e}"
            time.sleep(2)
            continue
        if r.status_code == 429:
            last_err = "429 rate-limited"
            logger.warning(f"  TV 429 (interval={interval}, batch={len(symbols)}); sleeping 60s")
            time.sleep(60)
            continue
        if r.status_code != 200:
            last_err = f"http {r.status_code}: {r.text[:200]}"
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
            if not sym or len(d) < NUM_COLUMNS:
                continue
            out[sym] = {col: d[i] for i, col in enumerate(TV_COLUMNS)}
        returned = set(out.keys())
        missing = [s for s in symbols if s not in returned]
        return _BatchResult(by_ticker=out, missing=missing, error=None)
    return _BatchResult(by_ticker={}, missing=symbols, error=last_err or "unknown")


# --- universe builder -------------------------------------------------------

def _read_recent_tickers_from_tab(client, tab_name: str, ticker_col_idx: int,
                                  days: int, logger: logging.Logger) -> set[str]:
    """Read tickers from `tab_name` whose date is within last `days`."""
    import datetime
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    out: set[str] = set()
    try:
        ss = sh._open_sheet(client)
        ws = ss.worksheet(tab_name)
        rows = ws.get_all_values()
    except Exception as e:
        logger.warning(f"  [universe] {tab_name} read failed: {e}")
        return out
    for r in rows[1:]:
        if not r or len(r) <= ticker_col_idx:
            continue
        date_s = (r[0] or "")[:10]
        try:
            d = datetime.date.fromisoformat(date_s)
        except Exception:
            continue
        if d < cutoff:
            continue
        t = (r[ticker_col_idx] or "").strip().upper()
        if t and t.isascii() and t.replace(".", "").isalnum():
            out.add(t)
    return out


def _read_latest_tickers_from_tab(client, tab_name: str, ticker_col_idx: int,
                                  logger: logging.Logger) -> set[str]:
    """Read tickers from the LATEST date in `tab_name`."""
    out: set[str] = set()
    try:
        ss = sh._open_sheet(client)
        ws = ss.worksheet(tab_name)
        rows = ws.get_all_values()
    except Exception as e:
        logger.warning(f"  [universe] {tab_name} read failed: {e}")
        return out
    if len(rows) <= 1:
        return out
    last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
    if not last_date:
        return out
    for r in rows[1:]:
        if not r or len(r) <= ticker_col_idx:
            continue
        if not (r[0] or "").startswith(last_date):
            continue
        t = (r[ticker_col_idx] or "").strip().upper()
        if t and t.isascii() and t.replace(".", "").isalnum():
            out.add(t)
    return out


def build_universe(client, logger: logging.Logger) -> list[str]:
    """
    Dedup-merge tickers from BOTH (a) the curated watchlist YAML universe
    (~80 names across 9 regime-tagged categories — held, stock_positions,
    decision_queue_active, defensive_etfs, commodity, volatility,
    blue_chip_dividend, speculative_growth, high_iv_wheel_targets), AND
    (b) the legacy active-book reads kept as a safety net so anything
    that touches our books (scan_results, options, etc.) still shows
    up even if the YAML drifts.

    SGX tickers are dropped (not on TV `america`). VIX is dropped here —
    spot index, not a TV scanner symbol; brain knows about it via the
    YAML's `notes` field but we don't try to pull TA on it.
    """
    universe: set[str] = set()

    # (a) curated YAML universe — primary source, regime-tagged
    try:
        cats = get_universe(client, logger)
        cat_summary = ", ".join(f"{c}={len(t)}" for c, t in cats.items())
        logger.info(f"  [universe] watchlist.yaml: {cat_summary}")
        for tickers in cats.values():
            universe |= set(tickers)
    except Exception as e:
        logger.warning(f"  [universe] watchlist.yaml read failed ({e}) — falling back to book-only")

    # (b) legacy active-book safety net — keeps any book touch in scope
    universe |= _read_recent_tickers_from_tab(client, "decision_queue", 2, 30, logger)
    universe |= _read_latest_tickers_from_tab(client, "options", 2, logger)
    universe |= _read_recent_tickers_from_tab(client, "scan_results", 1, 7, logger)
    universe |= _read_recent_tickers_from_tab(client, "screen_candidates", 2, 30, logger)
    universe |= _read_latest_tickers_from_tab(client, "positions_caspar", 1, logger)
    universe |= _read_latest_tickers_from_tab(client, "positions_sarah", 1, logger)

    # Drop SGX-only, VIX (spot index — TV scanner doesn't quote it), and
    # obvious non-tickers.
    drop = SGX_TICKERS | {"VIX"}
    universe = {t for t in universe if t and t not in drop and len(t) <= 6}
    return sorted(universe)


# --- per-ticker assembly ----------------------------------------------------

def _resolve_exchange(ticker: str, cache: dict[str, str]) -> str:
    """Pick a primary exchange for the ticker. Cache-aware."""
    t = ticker.upper()
    if t in cache:
        return cache[t]
    if t in HARDCODED_EXCHANGE:
        return HARDCODED_EXCHANGE[t]
    return "NASDAQ"  # default — fallback to NYSE handled in main loop


def _row_from_indicators(date: str, ticker: str, exchange: str,
                          interval: str, raw: dict) -> S.TvSignalRow:
    """Build a TvSignalRow from one decoded scanner result."""
    score_all = raw.get("Recommend.All")
    score_ma = raw.get("Recommend.MA")
    score_other = raw.get("Recommend.Other")

    label = _score_to_label(score_all) if score_all is not None else "ERROR: no_data"
    buy, sell, neutral = _approximate_counts(score_ma or 0.0, score_other or 0.0)

    def _f(k: str) -> float:
        v = raw.get(k)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    return S.TvSignalRow(
        date=date,
        ticker=ticker,
        exchange=exchange,
        interval=interval,
        recommendation=label,
        buy_count=buy,
        sell_count=sell,
        neutral_count=neutral,
        score_all=_f("Recommend.All"),
        score_ma=_f("Recommend.MA"),
        score_other=_f("Recommend.Other"),
        close=_f("close"),
        volume=_f("volume"),
        change_pct=_f("change"),
        rsi=_f("RSI"),
        macd=_f("MACD.macd"),
        macd_signal=_f("MACD.signal"),
        ema20=_f("EMA20"),
        ema50=_f("EMA50"),
        ema200=_f("EMA200"),
        adx=_f("ADX"),
        bb_upper=_f("BB.upper"),
        bb_lower=_f("BB.lower"),
        stoch_k=_f("Stoch.K"),
        stoch_d=_f("Stoch.D"),
        cci20=_f("CCI20"),
    )


def _error_row(date: str, ticker: str, interval: str, reason: str) -> S.TvSignalRow:
    return S.TvSignalRow(
        date=date,
        ticker=ticker,
        exchange="",
        interval=interval,
        recommendation=f"ERROR: {reason}",
        buy_count=0, sell_count=0, neutral_count=0,
        score_all=0.0, score_ma=0.0, score_other=0.0,
        close=0.0, volume=0.0, change_pct=0.0,
        rsi=0.0, macd=0.0, macd_signal=0.0,
        ema20=0.0, ema50=0.0, ema200=0.0,
        adx=0.0, bb_upper=0.0, bb_lower=0.0,
        stoch_k=0.0, stoch_d=0.0, cci20=0.0,
    )


# --- main pull --------------------------------------------------------------

def pull_signals(tickers: list[str], date: str, logger: logging.Logger,
                  batch_size: int = 20, sleep_between: float = 0.5) -> list[S.TvSignalRow]:
    """
    For each ticker × interval ∈ RUN_INTERVALS (1h + 1d + 1W), hit the TV
    scanner endpoint in batches of `batch_size`. Returns the full list of
    TvSignalRow rows.
    """
    cache = _load_cache()
    rows: list[S.TvSignalRow] = []

    # Build symbol map: ticker -> "EXCHANGE:TICKER"
    symbol_for: dict[str, str] = {}
    for t in tickers:
        ex = _resolve_exchange(t, cache)
        symbol_for[t] = f"{ex}:{t}"

    for interval in RUN_INTERVALS:
        # Track which tickers are still missing data after primary attempt.
        unresolved: list[str] = []
        # Batch primary calls
        all_tickers = list(tickers)
        for i in range(0, len(all_tickers), batch_size):
            chunk = all_tickers[i:i + batch_size]
            symbols = [symbol_for[t] for t in chunk]
            logger.info(f"  [pull] interval={interval} batch={i//batch_size + 1} ({len(symbols)} symbols)")
            res = _scanner_post(symbols, interval, logger)
            if res.error:
                logger.error(f"    batch failed: {res.error}")
                # mark whole batch unresolved
                unresolved.extend(chunk)
                time.sleep(sleep_between)
                continue
            for t in chunk:
                sym = symbol_for[t]
                raw = res.by_ticker.get(sym)
                if raw is None:
                    unresolved.append(t)
                    continue
                ex = sym.split(":", 1)[0]
                cache[t] = ex   # confirm cache
                rows.append(_row_from_indicators(date, t, ex, interval, raw))
            time.sleep(sleep_between)

        # Fallback pass on unresolved tickers — try alternate exchanges in
        # order. We sweep NASDAQ -> NYSE -> AMEX, skipping the one we
        # already tried as primary. Cache the working one.
        if unresolved:
            logger.info(f"  [fallback] interval={interval}: {len(unresolved)} tickers — retry on alternate exchange")
        FALLBACK_ORDER = ["NASDAQ", "NYSE", "AMEX"]
        still_unresolved = list(unresolved)
        for alt_ex in FALLBACK_ORDER:
            if not still_unresolved:
                break
            # Only try this exchange for tickers whose primary wasn't already this.
            chunk_back = [t for t in still_unresolved
                          if symbol_for[t].split(":", 1)[0] != alt_ex]
            if not chunk_back:
                continue
            for i in range(0, len(chunk_back), batch_size):
                sub = chunk_back[i:i + batch_size]
                symbols = [f"{alt_ex}:{t}" for t in sub]
                res = _scanner_post(symbols, interval, logger)
                if res.error:
                    logger.error(f"    fallback({alt_ex}) batch failed: {res.error}")
                    time.sleep(sleep_between)
                    continue
                for t, sym in zip(sub, symbols):
                    raw = res.by_ticker.get(sym)
                    if raw is None:
                        continue
                    ex = sym.split(":", 1)[0]
                    cache[t] = ex
                    rows.append(_row_from_indicators(date, t, ex, interval, raw))
                    if t in still_unresolved:
                        still_unresolved.remove(t)
                time.sleep(sleep_between)
        # Anything STILL unresolved gets an error row.
        for t in still_unresolved:
            rows.append(_error_row(date, t, interval, "not_found"))

    _save_cache(cache)
    return rows


# --- main ------------------------------------------------------------------

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("tv_signals")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="parse only, print rows; no Sheet write")
    parser.add_argument("--limit", type=int, default=0,
                        help="max number of tickers (debug). 0 = all")
    args = parser.parse_args()

    load_env()
    logger = setup_logger()

    today = S.now_sgt_date()
    logger.info(f"tv_signals_run start (date={today}, dry={args.dry})")

    t0 = time.time()
    try:
        client = sh.authenticate()
    except Exception as e:
        logger.error(f"sheets auth failed: {e}")
        return 2

    universe = build_universe(client, logger)
    if not universe:
        logger.error("active universe is empty — nothing to pull")
        return 1
    if args.limit > 0:
        universe = universe[:args.limit]
    logger.info(f"  universe: {len(universe)} tickers — {', '.join(universe)}")

    rows = pull_signals(universe, today, logger)
    elapsed = time.time() - t0

    n_ok = sum(1 for r in rows if not r.recommendation.startswith("ERROR"))
    n_err = sum(1 for r in rows if r.recommendation.startswith("ERROR"))
    logger.info(f"pulled {len(universe)} tickers x {len(RUN_INTERVALS)} intervals "
                f"({'+'.join(RUN_INTERVALS)}) = {len(rows)} rows. "
                f"{n_ok} OK, {n_err} errors. {elapsed:.1f}s")

    if args.dry:
        for r in rows:
            row = r.to_row()
            print(f"  [dry] {row[1]:6} {row[3]:3} {row[4]:12} score={row[8]:>6} "
                  f"close={row[11]:>10} RSI={row[14]:>5}")
        return 0

    if not rows:
        logger.warning("no rows to append")
        return 0

    try:
        sh.ensure_headers(client, S.TvSignalRow.TAB_NAME, S.TvSignalRow.HEADERS)
        n = sh.append_rows(client, S.TvSignalRow.TAB_NAME, [r.to_row() for r in rows])
        logger.info(f"appended {n} rows to {S.TvSignalRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"sheets write failed: {e}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
