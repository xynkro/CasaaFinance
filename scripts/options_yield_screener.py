#!/usr/bin/env python3
"""
options_yield_screener.py — Wide-universe CSP/CC candidate generator.

Why this exists:
  The brain proposes 0 new CSP/CC strategies because nothing GENERATES
  fresh option-strategy candidates. `vcp-screener` and `canslim-screener`
  find STOCK candidates only. This script scans a wide wheel-target
  universe for high-yield CSP/CC setups and surfaces top 20 to the
  `options_yield_candidates` sheet so the WSR brain can propose them as
  fresh CSP/CC entries.

Logic:
  1. Load wide universe via `src.watchlist.get_universe()` if available;
     otherwise fall back to a hardcoded curated list.
  2. For each ticker, fetch via yfinance:
       - 60-day history → realized vol → IV proxy
       - Option chain for expiries in the 25-50 DTE window
       - OTM puts (CSP) and OTM calls (CC, gated by trading_rules bucket)
  3. Compute Black-Scholes delta (math.erf-based normal CDF — no scipy).
     Premium = (bid+ask)/2; annual yield = premium/strike × 365/dte × 100.
     IV rank approximated from current-vs-realized vol band.
  4. Filter:
       dte ∈ [25, 50], abs(delta) ∈ [0.18, 0.32], bid > 0.05,
       iv_rank ≥ 30, spread_pct ≤ 0.20.
       For CCs, ticker bucket must be in cc_eligible_buckets per
       src/trading_rules.py — DO NOT propose CCs on SCHD/blue_chip/
       leveraged_etf.
  5. Score (0-100) by yield + IV rank + delta sweet-spot + spread + OI.
  6. Top 20 written to `options_yield_candidates` sheet with rationale.

Usage:
  python scripts/options_yield_screener.py            # live write
  python scripts/options_yield_screener.py --dry      # print only

Cron: .github/workflows/options-yield.yml — Sunday 12:00 UTC, between
screen-candidates.yml (11:00 UTC) and wsr-full.yml (11:37 UTC).
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src import schema as S          # noqa: E402
from src import sheets as sh         # noqa: E402
from src.sync import load_env        # noqa: E402
from src.bsm import norm_cdf         # noqa: E402
from src.logging_util import setup_logging  # noqa: E402


# ──────────────────── Tunables ────────────────────────────────────────────

DTE_MIN = 25
DTE_MAX = 50
DELTA_MIN = 0.18
DELTA_MAX = 0.32
DELTA_TARGET = 0.25
MIN_BID = 0.30       # $0.05 was producing garbage penny-premium picks
MIN_IV_RANK = 30.0
MAX_SPREAD_PCT = 0.20            # fractional (bid-ask)/mid
MIN_OI_FOR_BONUS = 100
MAX_TOP = 20
INTER_TICKER_SLEEP = 0.5         # seconds between tickers (politeness)
MAX_WORKERS = 3                  # concurrent yfinance fetches

# Hardcoded fallback universe used if `src.watchlist.get_universe()` fails.
# Mix of held tickers + curated wheel-target names.
HARDCODED_FALLBACK = [
    # Held wheel candidates
    "BBAI", "BTBT", "OPEN", "RCAT", "AAPL", "BYND", "SBET", "HIMS",
    # Curated wheel-target list per spec
    "F", "T", "BAC", "WFC", "INTC", "MU", "PYPL", "U", "RBLX", "SOFI",
    "RIVN", "AFRM", "SHOP", "COIN", "AMD", "NVDA", "TSLA", "MSFT",
    "AAPL", "GOOGL", "META", "NFLX", "AMZN", "JPM", "V", "MA",
]

# Ticker → bucket map + gates now live in src/trading_rules.py (single source
# of truth, shared with daily_options_scan). Aliased here for backward compat.
from src.trading_rules import TICKER_BUCKET, bucket_for as _bucket_for  # noqa: E402,F401


# ──────────────────── Math helpers ────────────────────────────────────────

def bs_delta(S: float, K: float, T: float, sigma: float, r: float, right: str) -> float:
    """Black-Scholes delta. `right` is 'C' or 'P'. Returns signed delta."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError):
        return 0.0
    if right == "C":
        return norm_cdf(d1)
    return norm_cdf(d1) - 1.0


def _realized_vol_annual(closes: list[float], lookback: int = 60) -> float:
    """Annualized realized vol from daily log returns over `lookback` days."""
    if len(closes) < 5:
        return 0.0
    series = closes[-lookback:] if len(closes) >= lookback else closes
    rets: list[float] = []
    for a, b in zip(series[:-1], series[1:]):
        if a > 0 and b > 0:
            rets.append(math.log(b / a))
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    daily_vol = math.sqrt(max(var, 0.0))
    return daily_vol * math.sqrt(252.0)


# ──────────────────── Universe loading ────────────────────────────────────


def _blend_gov_confluence_tickers(base: list[str], logger: logging.Logger) -> list[str]:
    """Add gov_confluence_signals tickers (last 7d) to the scan universe.

    Defense primes and gov-contractor names with fresh contract activity
    should be scanned for options opportunities even if they're not in the
    user's portfolio or watchlist YAML.
    """
    try:
        import datetime as _dt
        client = sh.authenticate()
        ss = sh._open_sheet(client)
        ws = ss.worksheet(S.GovConfluenceSignalRow.TAB_NAME)
        rows = ws.get_all_values()
        if len(rows) < 2:
            return base
        hdr = rows[0]
        cols = {h: i for i, h in enumerate(hdr)}
        seven_d = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
        existing = {t.upper() for t in base}
        added = 0
        for r in rows[1:]:
            if len(r) <= cols.get("date", 0) or r[cols["date"]] < seven_d:
                continue
            tk = r[cols["ticker"]].strip().upper()
            # Only add US-listed, alphabetic tickers (skip SGX, etc.)
            if tk and tk not in existing and len(tk) <= 5 and tk.isalpha():
                base.append(tk)
                existing.add(tk)
                added += 1
        if added:
            logger.info(f"  +{added} tickers from gov_confluence_signals → universe")
    except Exception as e:
        logger.debug(f"gov confluence universe blend skipped: {e}")
    return base


def load_universe(logger: logging.Logger) -> list[str]:
    """
    Try `src.watchlist.get_universe()`; fall back to hardcoded list if
    unavailable or empty. We blend held + decision_queue + a curated
    wheel-target pool so the brain sees the full cross-section.
    """
    try:
        from src.watchlist import get_universe, flatten  # type: ignore
        # get_universe needs a sheets client to resolve __from_sheets_*__
        # sentinels. If sheet auth fails, we still have the YAML's hardcoded
        # category lists.
        try:
            client = sh.authenticate()
        except Exception as e:
            logger.warning(f"sheet auth failed for universe ({e}); using YAML fallbacks only")
            client = None
        universe = get_universe(client, logger=logger) if client else {}
        # If sheet auth failed, get_universe is bypassed — read YAML directly.
        if not universe:
            try:
                import yaml
                yaml_path = _PROJECT_ROOT / "prompts" / "watchlist.yaml"
                cfg = yaml.safe_load(yaml_path.read_text()) or {}
                sections = cfg.get("universe") or {}
                fallback_pool: list[str] = []
                for body in sections.values():
                    body = body or {}
                    fallback_pool.extend(body.get("tickers") or [])
                    fallback_pool.extend(body.get("fallback") or [])
                universe = {"yaml_fallback": fallback_pool}
            except Exception as e:
                logger.warning(f"YAML fallback failed too ({e}); using hardcoded list")
                universe = {}
        flat = flatten(universe) if universe else []
        if flat:
            logger.info(f"loaded {len(flat)} tickers from watchlist module")
            # Blend gov confluence tickers into the universe
            flat = _blend_gov_confluence_tickers(flat, logger)
            return flat
    except ImportError:
        logger.info("src.watchlist not importable — using hardcoded fallback")
    except Exception as e:
        logger.warning(f"watchlist load raised {e}; using hardcoded fallback")

    # Hardcoded fallback (de-duped)
    seen: set[str] = set()
    out: list[str] = []
    for t in HARDCODED_FALLBACK:
        u = t.upper()
        if u not in seen:
            seen.add(u)
            out.append(u)
    logger.info(f"using hardcoded fallback universe: {len(out)} tickers")
    # Blend in gov confluence tickers so defense/gov-contractor names
    # with fresh contract activity get scanned for options opportunities
    out = _blend_gov_confluence_tickers(out, logger)
    return out


# ──────────────────── yfinance fetching ───────────────────────────────────

def _fetch_underlying(ticker: str, logger: logging.Logger) -> Optional[dict]:
    """
    Pull current spot + 60-day closes for a ticker. Returns None on failure.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        # 90 calendar days ≈ 60 trading days
        hist = t.history(period="90d", interval="1d", auto_adjust=False)
    except Exception as e:
        logger.debug(f"  {ticker}: history fetch failed: {e}")
        return None

    if hist is None or len(hist) < 5:
        return None

    closes = [float(x) for x in hist["Close"].dropna().tolist() if x and x > 0]
    if len(closes) < 5:
        return None
    spot = closes[-1]
    sigma = _realized_vol_annual(closes, 60) * 1.10  # 1.1× multiplier per spec
    return {
        "ticker": ticker,
        "spot": spot,
        "closes": closes,
        "sigma_proxy": sigma,
    }


def _pick_expiries(expiries: tuple[str, ...]) -> list[str]:
    """
    Return up to 3 expiry strings whose DTE falls in [DTE_MIN, DTE_MAX],
    closest to a 35-DTE midpoint first.
    """
    today = date.today()
    cands: list[tuple[int, str]] = []
    for exp in expiries:
        try:
            ed = datetime.strptime(exp, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (ed - today).days
        if DTE_MIN <= dte <= DTE_MAX:
            cands.append((dte, exp))
    cands.sort(key=lambda x: abs(x[0] - 35))
    return [exp for _, exp in cands[:3]]


def _candidates_from_chain(
    ticker: str,
    expiry_iso: str,
    right: str,           # "P" (CSP) or "C" (CC)
    spot: float,
    sigma_proxy: float,
    logger: logging.Logger,
) -> list[dict]:
    """
    Walk the option chain at one expiry+right and return per-strike candidate
    dicts that satisfy the OTM + delta + liquidity gates.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        chain = t.option_chain(expiry_iso)
    except Exception as e:
        logger.debug(f"  {ticker} {expiry_iso} {right}: chain fetch failed: {e}")
        return []

    df = chain.puts if right == "P" else chain.calls
    if df is None or df.empty:
        return []

    today = date.today()
    try:
        ed = datetime.strptime(expiry_iso, "%Y-%m-%d").date()
    except ValueError:
        return []
    dte = (ed - today).days
    if dte < DTE_MIN or dte > DTE_MAX:
        return []
    T = max(dte, 1) / 365.0

    out: list[dict] = []
    for _, row in df.iterrows():
        try:
            K = float(row.get("strike") or 0)
            if K <= 0:
                continue

            # OTM filter
            if right == "P":
                if K >= spot:
                    continue       # not OTM
            else:
                if K <= spot:
                    continue       # not OTM

            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            last_p = float(row.get("lastPrice", 0) or 0)
            volume = int(row.get("volume", 0) or 0)
            oi = int(row.get("openInterest", 0) or 0)
            iv_chain = float(row.get("impliedVolatility", 0) or 0)

            # Liquidity / mid-price
            if bid <= MIN_BID:
                continue
            if ask <= 0 or ask < bid:
                continue
            mid = (bid + ask) / 2
            if mid <= 0:
                continue
            spread_pct = (ask - bid) / mid if mid > 0 else 1.0
            if spread_pct > MAX_SPREAD_PCT:
                continue

            # IV — prefer chain IV, fall back to realized-vol proxy
            iv_for_delta = iv_chain if 0.05 < iv_chain < 3.0 else sigma_proxy
            if iv_for_delta <= 0:
                continue
            iv_for_record = iv_chain if 0.05 < iv_chain < 3.0 else sigma_proxy

            delta = bs_delta(spot, K, T, iv_for_delta, 0.045, right)
            delta_mag = abs(delta)
            if delta_mag < DELTA_MIN or delta_mag > DELTA_MAX:
                continue

            annual_yield = (mid / K) * (365.0 / max(dte, 1)) * 100.0

            out.append({
                "ticker": ticker,
                "right": right,
                "strike": K,
                "expiry_iso": expiry_iso,
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": last_p,
                "iv": iv_for_record,
                "iv_chain": iv_chain,
                "delta": delta,
                "delta_mag": delta_mag,
                "spread_pct": spread_pct,
                "volume": volume,
                "open_interest": oi,
                "annual_yield_pct": annual_yield,
                "spot": spot,
                "sigma_proxy": sigma_proxy,
            })
        except (ValueError, KeyError, TypeError):
            continue

    return out


# ──────────────────── IV rank approximation ───────────────────────────────

def _approx_iv_rank(iv_now: float, sigma_proxy: float) -> float:
    """
    IV rank without 1Y IV history.

    `sigma_proxy` is realized vol × 1.10 — i.e. an estimate of "fair" IV
    given the past 60 days of price action. We treat it as the midpoint
    of an implied IV-history band and map current IV to a percentile:

        ratio = iv_now / sigma_proxy
        ratio  0.6 → rank   0
        ratio  1.0 → rank  50  (current IV at par with realized proxy)
        ratio  1.4 → rank 100  (current IV 40% above proxy = high IV rank)

    Capped to [0, 100]. This is intentionally generous on the upside —
    when chain IV is well above realized vol, premiums are actually rich,
    so the rank should reflect that. The brain still owns final selection.
    """
    if iv_now <= 0 or sigma_proxy <= 0:
        return 0.0
    ratio = iv_now / max(sigma_proxy, 1e-6)
    # Map ratio band [0.6, 1.4] → [0, 100] with 1.0 = 50.
    rank = (ratio - 0.6) / (1.4 - 0.6) * 100.0
    return max(0.0, min(100.0, rank))


# ──────────────────── Scoring ────────────────────────────────────────────

def score_candidate(c: dict) -> float:
    """
    score = (annual_yield_pct * 2)              # max ~50 (high yield)
          + (iv_rank * 0.3)                     # max 30 (rich IV)
          + (-abs(delta - 0.25) * 100)          # max ~5 at 0.25Δ
          + (-spread_pct * 100)                 # spread penalty
          + (volume_score)                      # +0-15 for OI > 100
    """
    yield_pts = min(50.0, c["annual_yield_pct"] * 2.0)
    iv_pts = min(30.0, c["iv_rank"] * 0.3)
    delta_pen = -abs(c["delta_mag"] - DELTA_TARGET) * 100.0   # negative or 0
    spread_pen = -c["spread_pct"] * 100.0
    oi = c["open_interest"]
    if oi >= 1000:
        liq_pts = 15.0
    elif oi >= 500:
        liq_pts = 10.0
    elif oi >= MIN_OI_FOR_BONUS:
        liq_pts = 5.0
    else:
        liq_pts = 0.0
    raw = yield_pts + iv_pts + delta_pen + spread_pen + liq_pts
    # Clamp to [0, 100] for display
    return max(0.0, min(100.0, raw))


# ──────────────────── CC eligibility ────────────────────────────────────

# ──────────────────── Signal gates (TV + analyst) ────────────────────────
# Mid-flight gates so we don't propose CSPs on STRONG_SELL names (where
# assignment becomes likely at a loss to fair value) or CCs on STRONG_BUY
# names (where we'd cap upside in a real breakout). Reads two sheets once
# at startup and caches per-ticker for the scan loop.

# TV recommendations we treat as "directional veto":
#   - CSP must NOT see these (selling puts in a downtrend = paid to catch a falling knife)
#   - CC must NOT see the inverse (selling calls in an uptrend = capping a winner)
TV_BEARISH = {"SELL", "STRONG_SELL"}
TV_BULLISH = {"BUY", "STRONG_BUY"}

# Analyst consensus floor for CSPs. consensus_score range is [-2, +2]:
#   -2 = STRONG_SELL, -1 = SELL, 0 = HOLD, +1 = BUY, +2 = STRONG_BUY
# Requiring >= 0.5 means at least "leaning BUY" — we won't be assigned to
# a name Wall St considers HOLD-or-worse.
ANALYST_CSP_MIN_SCORE = 0.5


def _load_signal_gates(logger: logging.Logger) -> tuple[dict[str, str], dict[str, float], dict[str, dict]]:
    """Read TV daily signals + analyst consensus + gov confluence per-ticker.

    Returns:
        (tv_daily_by_ticker, analyst_score_by_ticker, gov_confluence_by_ticker)
        Missing tickers default to NEUTRAL TV, 0.0 analyst, {} gov (no veto).
        Gov confluence dict per ticker: {score, tier, congress_sell_count,
        contract_dollars, strategy}.
    """
    from src import sheets as sh

    tv_daily: dict[str, str] = {}
    analyst: dict[str, float] = {}
    gov: dict[str, dict] = {}

    client = sh.authenticate()
    ss = sh._open_sheet(client)

    # tv_signals — keep only interval=1d, latest row per ticker
    try:
        ws = ss.worksheet(S.TvSignalRow.TAB_NAME)
        rows = ws.get_all_values()
        if len(rows) > 1:
            hdr = rows[0]
            c_tk = hdr.index("ticker")
            c_iv = hdr.index("interval")
            c_rec = hdr.index("recommendation")
            c_date = hdr.index("date") if "date" in hdr else -1
            # Take latest date per (ticker, interval=1d). Use string sort
            # since audit_ts is YYYY-MM-DDTHHMMSS-sortable.
            by_ticker: dict[str, tuple[str, str]] = {}
            for r in rows[1:]:
                if len(r) <= max(c_tk, c_iv, c_rec):
                    continue
                if r[c_iv] != "1d":
                    continue
                tk = r[c_tk].upper()
                ts = r[c_date] if c_date >= 0 and len(r) > c_date else ""
                rec = r[c_rec].upper()
                prev = by_ticker.get(tk)
                if prev is None or ts > prev[0]:
                    by_ticker[tk] = (ts, rec)
            tv_daily = {tk: rec for tk, (_, rec) in by_ticker.items()}
            logger.info(f"  signal gates: loaded {len(tv_daily)} TV daily signals")
    except Exception as e:
        logger.warning(f"  signal gates: TV signals unavailable ({e}) — directional gate disabled")

    # analyst_consensus — upserted by ticker so every row is current
    try:
        ws = ss.worksheet(S.AnalystConsensusRow.TAB_NAME)
        rows = ws.get_all_values()
        if len(rows) > 1:
            hdr = rows[0]
            c_tk = hdr.index("ticker")
            c_score = hdr.index("consensus_score")
            for r in rows[1:]:
                if len(r) <= max(c_tk, c_score):
                    continue
                tk = r[c_tk].upper()
                try:
                    analyst[tk] = float(r[c_score])
                except (ValueError, TypeError):
                    pass
            logger.info(f"  signal gates: loaded {len(analyst)} analyst consensus scores")
    except Exception as e:
        logger.warning(f"  signal gates: analyst consensus unavailable ({e}) — analyst gate disabled")

    # gov_confluence_signals — latest score + congress sell context per ticker
    try:
        import datetime
        ws = ss.worksheet(S.GovConfluenceSignalRow.TAB_NAME)
        rows = ws.get_all_values()
        if len(rows) > 1:
            hdr = rows[0]
            cols = {h: i for i, h in enumerate(hdr)}
            seven_d = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
            for r in rows[1:]:
                if len(r) <= cols.get("date", 0):
                    continue
                if r[cols["date"]] < seven_d:
                    continue
                tk = r[cols["ticker"]].upper()
                try:
                    score = float(r[cols["confluence_score"]] or 0)
                except (TypeError, ValueError):
                    score = 0.0
                prev = gov.get(tk)
                if prev is None or score > prev.get("score", 0):
                    gov[tk] = {
                        "score": score,
                        "tier": r[cols.get("tier", len(r))] if "tier" in cols and cols["tier"] < len(r) else "",
                        "strategy": r[cols.get("recommended_strategy", len(r))] if "recommended_strategy" in cols and cols["recommended_strategy"] < len(r) else "",
                    }
            logger.info(f"  signal gates: loaded {len(gov)} gov confluence signals (last 7d)")
    except Exception as e:
        logger.warning(f"  signal gates: gov confluence unavailable ({e}) — gov gate disabled")

    return tv_daily, analyst, gov


def _signal_gate(
    strategy: str,
    ticker: str,
    tv_daily: dict[str, str],
    analyst: dict[str, float],
    gov: dict[str, dict] | None = None,
) -> tuple[bool, str]:
    """Return (blocked, reason). Empty reason when allowed.

    CSP blocked when:
      - TV daily ∈ {SELL, STRONG_SELL}  (selling puts into a downtrend)
      - Analyst consensus < 0.5         (Wall St not even leaning BUY)
      - Congress cluster selling (gov confluence indicates TRIM)
    CC blocked when:
      - TV daily ∈ {BUY, STRONG_BUY}    (selling calls in a real breakout)
      - Gov confluence Tier A/B BUY_DIP  (don't cap a govt-contract winner)
    """
    tv = tv_daily.get(ticker, "")  # missing → no veto
    gov_info = (gov or {}).get(ticker, {})
    gov_strategy = gov_info.get("strategy", "")

    if strategy == "CSP":
        if tv in TV_BEARISH:
            return True, f"CSP blocked: TV daily = {tv} (don't sell puts into a downtrend)"
        score = analyst.get(ticker, 0.0)
        if score < ANALYST_CSP_MIN_SCORE:
            return True, f"CSP blocked: analyst consensus {score:.2f} < {ANALYST_CSP_MIN_SCORE} (not enough Wall St conviction)"
        # Congress selling a name we'd sell puts on → red flag
        if gov_strategy == "TRIM":
            return True, f"CSP blocked: Congress cluster selling (gov confluence → TRIM)"
    elif strategy == "CC":
        if tv in TV_BULLISH:
            return True, f"CC blocked: TV daily = {tv} (don't cap a winner)"
        # Don't sell calls on names with fresh gov contract catalysts
        gov_tier = gov_info.get("tier", "")
        if gov_tier in ("A", "B") and gov_strategy in ("BUY_DIP", "LONG_CALL", "PMCC"):
            return True, f"CC blocked: gov confluence Tier {gov_tier} {gov_strategy} (don't cap a contract catalyst)"
    return False, ""


# Bucket eligibility gates now live in src/trading_rules.py (single source of
# truth, shared with daily_options_scan). Re-exported here for backward compat.
from src.trading_rules import (  # noqa: E402
    cc_blocked_by_bucket,
    csp_blocked_by_bucket,
)


# ──────────────────── Per-ticker pipeline ────────────────────────────────

def scan_ticker(
    ticker: str,
    logger: logging.Logger,
    tv_daily: dict[str, str] | None = None,
    analyst: dict[str, float] | None = None,
    gov: dict[str, dict] | None = None,
) -> list[dict]:
    """
    Returns a list of fully-scored candidate dicts (CSP and/or CC) for one
    ticker. Empty list if nothing qualifies.

    `tv_daily` and `analyst` are the per-ticker signal gates loaded once at
    startup (see `_load_signal_gates`). Missing dicts disables the gates —
    useful for unit tests / one-off scans.
    """
    import yfinance as yf

    base = _fetch_underlying(ticker, logger)
    if not base:
        logger.debug(f"  {ticker}: no underlying data")
        return []

    spot = base["spot"]
    sigma_proxy = base["sigma_proxy"]
    if spot <= 0 or sigma_proxy <= 0:
        return []
    if spot < 10.0:
        logger.debug(f"  {ticker}: spot ${spot:.2f} < $10 — premiums too thin for income")
        return []

    try:
        t = yf.Ticker(ticker)
        all_exps = tuple(t.options or ())
    except Exception as e:
        logger.debug(f"  {ticker}: options list failed: {e}")
        return []
    target_exps = _pick_expiries(all_exps)
    if not target_exps:
        return []

    cc_blocked, cc_reason = cc_blocked_by_bucket(ticker)
    csp_blocked, csp_reason = csp_blocked_by_bucket(ticker)
    bucket = _bucket_for(ticker)

    # Apply signal gates (TV daily + analyst consensus + gov confluence).
    # These are layered on top of bucket gates — bucket says "is this name
    # CSP/CC-eligible in principle?" while the signal gate says "given
    # current technicals/consensus/gov data, is the trade aligned today?"
    if tv_daily is not None and analyst is not None:
        if not csp_blocked:
            blocked, reason = _signal_gate("CSP", ticker, tv_daily, analyst, gov)
            if blocked:
                csp_blocked, csp_reason = True, reason
                logger.debug(f"  {ticker}: {reason}")
        if not cc_blocked:
            blocked, reason = _signal_gate("CC", ticker, tv_daily, analyst, gov)
            if blocked:
                cc_blocked, cc_reason = True, reason
                logger.debug(f"  {ticker}: {reason}")

    raw_candidates: list[dict] = []
    for exp in target_exps:
        # CSPs (skip if bucket OR signal gate blocks)
        if not csp_blocked:
            for c in _candidates_from_chain(ticker, exp, "P", spot, sigma_proxy, logger):
                c["strategy"] = "CSP"
                c["bucket"] = bucket
                raw_candidates.append(c)
        # CCs (skip if bucket OR signal gate blocks)
        if not cc_blocked:
            for c in _candidates_from_chain(ticker, exp, "C", spot, sigma_proxy, logger):
                c["strategy"] = "CC"
                c["bucket"] = bucket
                raw_candidates.append(c)

    if not raw_candidates:
        if cc_blocked and csp_blocked:
            logger.debug(f"  {ticker}: {cc_reason}; {csp_reason}")

    # Apply IV-rank filter + score
    ranked: list[dict] = []
    for c in raw_candidates:
        c["iv_rank"] = _approx_iv_rank(c["iv"], sigma_proxy)
        if c["iv_rank"] < MIN_IV_RANK:
            continue
        c["score"] = score_candidate(c)
        ranked.append(c)

    # Per-ticker dedupe: prefer the highest-scoring candidate per
    # (strategy, expiry) so we don't flood the sheet with multiple
    # adjacent strikes from the same expiry.
    by_key: dict[tuple, dict] = {}
    for c in ranked:
        key = (c["strategy"], c["expiry_iso"])
        prev = by_key.get(key)
        if prev is None or c["score"] > prev["score"]:
            by_key[key] = c
    deduped = list(by_key.values())

    return deduped


# ──────────────────── Build sheet rows ────────────────────────────────────

def _build_rationale(c: dict) -> str:
    """One-line "why this candidate" string."""
    iv_rank = c["iv_rank"]
    if iv_rank >= 70:
        iv_word = "very rich"
    elif iv_rank >= 50:
        iv_word = "rich"
    elif iv_rank >= 35:
        iv_word = "elevated"
    else:
        iv_word = "modest"
    return (
        f"{c['strategy']} — IV rank {iv_rank:.0f} {iv_word}; "
        f"{c['dte']} DTE {abs(c['delta']):.2f}Δ at "
        f"${c['strike']:.2f} strike; "
        f"{c['annual_yield_pct']:.1f}% annual yield."
    )[:500]


def to_schema_row(c: dict, today_iso: str) -> S.OptionsYieldCandidateRow:
    return S.OptionsYieldCandidateRow(
        date=today_iso,
        ticker=c["ticker"],
        strategy=c["strategy"],
        right=c["right"],
        strike=float(c["strike"]),
        expiry=c["expiry_iso"].replace("-", ""),
        dte=int(c["dte"]),
        underlying_last=float(c["spot"]),
        delta=float(c["delta"]),
        premium=float(c["mid"]),
        annual_yield_pct=float(c["annual_yield_pct"]),
        iv=float(c["iv"]),
        iv_rank=float(c["iv_rank"]),
        moneyness="OTM",
        spread_pct=float(c["spread_pct"]),
        open_interest=int(c["open_interest"]),
        volume=int(c["volume"]),
        score=float(c["score"]),
        rationale=_build_rationale(c),
    )


# ──────────────────── Main ────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="parse only, print rows that would be appended; no Sheet write")
    parser.add_argument("--limit", type=int, default=0,
                        help="cap number of tickers to scan (0 = all). useful for local smoke tests.")
    args = parser.parse_args()

    load_env()
    logger = setup_logging("options_yield_screener")
    today_iso = S.now_sgt_date()
    logger.info(f"options_yield_screener start (date={today_iso}, dry={args.dry})")

    universe = load_universe(logger)
    if args.limit > 0:
        universe = universe[: args.limit]
    if not universe:
        logger.warning("empty universe — nothing to scan")
        return 0

    # Filter out non-US listings (e.g. .SI tickers don't have US options).
    us_universe = [t for t in universe if "." not in t and "-" not in t.replace("-B", "")]
    logger.info(f"scanning {len(us_universe)} US-listed tickers (from {len(universe)} total)")

    # Load TV daily + analyst consensus once for the directional gates.
    # Missing sheets are non-fatal — the gates just no-op.
    tv_daily, analyst, gov = _load_signal_gates(logger)

    all_candidates: list[dict] = []

    # Run with bounded concurrency. yfinance is slow; ThreadPoolExecutor
    # speeds up the I/O-bound option-chain fetches without hammering
    # Yahoo's rate-limiter (max_workers=3 + sleep between submissions).
    def _wrapped(t: str) -> list[dict]:
        try:
            return scan_ticker(t, logger, tv_daily=tv_daily, analyst=analyst, gov=gov)
        except Exception as e:
            logger.warning(f"  {t}: scan_ticker raised {e}")
            return []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = []
        for i, ticker in enumerate(us_universe):
            futures.append(pool.submit(_wrapped, ticker))
            # Politeness — slow down submission, not the workers themselves
            if i and i % MAX_WORKERS == 0:
                time.sleep(INTER_TICKER_SLEEP)
        for fut in as_completed(futures):
            cands = fut.result()
            if cands:
                t = cands[0]["ticker"]
                logger.info(
                    f"  {t}: {len(cands)} candidate(s) "
                    f"(top score {max(c['score'] for c in cands):.1f})"
                )
                all_candidates.extend(cands)

    if not all_candidates:
        logger.warning("no candidates passed filters — nothing to write")
        return 0

    # Sort all candidates by score desc, keep top MAX_TOP
    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    top = all_candidates[:MAX_TOP]
    logger.info(f"top {len(top)} of {len(all_candidates)} total candidates")

    # Build sheet rows
    rows = [to_schema_row(c, today_iso) for c in top]

    if args.dry:
        for r in rows:
            print(f"  [dry] {r.to_row()}")
        # Plus a human-readable rationale list
        print("\n=== TOP CANDIDATES ===")
        for c in top:
            print(
                f"  {c['ticker']:<6} {c['strategy']} {c['right']} "
                f"${c['strike']:>7.2f} exp={c['expiry_iso']} dte={c['dte']:>2} "
                f"|Δ|={c['delta_mag']:.2f} prem=${c['mid']:.2f} "
                f"yield={c['annual_yield_pct']:>5.1f}% IVr={c['iv_rank']:>3.0f} "
                f"score={c['score']:>5.1f}"
            )
        return 0

    try:
        client = sh.authenticate()
        sh.ensure_headers(client, S.OptionsYieldCandidateRow.TAB_NAME,
                          S.OptionsYieldCandidateRow.HEADERS)
        n = sh.append_rows(client, S.OptionsYieldCandidateRow.TAB_NAME,
                           [r.to_row() for r in rows])
        logger.info(f"appended {n} rows to {S.OptionsYieldCandidateRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"sheets write failed: {e}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
