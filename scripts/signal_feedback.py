#!/usr/bin/env python3
"""
signal_feedback.py — Strategy Signal Feedback Loop

Matches historical scanner picks (scan_results) against forward price
outcomes to evaluate whether each pick's signals predicted correctly.

Phase 1: Data collection
  - Read scan_results from sheet (last 90 days)
  - For mature picks (past expiry or >30d old), fetch yfinance data
  - Re-derive the 16 signal values using compute_indicators + compute_signals
  - Compute strategy-specific outcome (WIN/LOSS/SCRATCH)
  - Write to signal_outcomes sheet
  - Send Telegram summary with key findings

Phase 2 (future, needs data accumulation):
  - OLS regression: outcome ~ beta_i * signal_i
  - Compare empirical betas to STRATEGY_WEIGHTS
  - Suggest weight adjustments

Usage:
    python scripts/signal_feedback.py [--dry] [--days 90] [--force]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import sheets as sh
from src import schema as S
from src.indicators import compute_indicators
from src.option_pnl import csp_settle_pct, cc_settle_pct
from src.technical_score import compute_signals, STRATEGY_WEIGHTS

logger = logging.getLogger("signal_feedback")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Constants ──────────────────────────────────────────────────────────────

# Minimum days after scan before we evaluate outcome.
# CSP/CC: use DTE (evaluate at expiry). BUY: fixed 30d window.
BUY_EVAL_DAYS = 30
MIN_EVAL_DAYS = 5  # don't evaluate anything less than 5 days old

# Outcome thresholds — a trade within ±PNL_SCRATCH_EPS% of breakeven is a SCRATCH.
# Defined on P&L (not price distance from the strike) so the kept premium is never
# thrown away. Matches option_scanner.KELLY_SCRATCH_EPS so a row labelled SCRATCH
# here is also the row Kelly drops from both buckets — one breakeven band system-wide.
PNL_SCRATCH_EPS = 0.10

# yfinance rate limiting — pause between ticker downloads
YF_DELAY_S = 0.3

# Selection-skill grading (_grade_selection_skill — the user-decisions feedback
# loop). A real fill/kill/defer decision is JOINed to a graded pick by
# ticker+strategy+strike when the decision lands within this many days of the
# pick's scan date. Below SELECTION_MIN_GRADED matched WIN/LOSS pairs the metric
# is suppressed as too noisy to act on. Both are deliberately tunable: widen the
# window if decisions are logged late, raise the floor before trusting the edge.
SELECTION_MATCH_WINDOW_DAYS = 10
SELECTION_MIN_GRADED = 5


# ── Sheet reading helpers ──────────────────────────────────────────────────

def _read_tab(client, tab_name: str) -> list[dict]:
    """Read a sheet tab and return list of dicts keyed by header row."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(tab_name)
    except Exception:
        logger.warning(f"Tab '{tab_name}' not found")
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    headers = rows[0]
    out = []
    for r in rows[1:]:
        d = {}
        for i, h in enumerate(headers):
            d[h] = r[i] if i < len(r) else ""
        out.append(d)
    return out


def _parse_date(date_str: str) -> datetime | None:
    """Parse a date string that may have THHMMSS audit suffix."""
    if not date_str:
        return None
    # Strip audit suffix: "2026-05-20T143022" → "2026-05-20"
    base = date_str[:10]
    try:
        return datetime.strptime(base, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


# ── Firestore decision write-back (the real-user feedback loop) ──────────────
# The PWA mirrors every fill/kill/defer into the `decisions` Firestore
# collection (doc id = decision_key = date|account|ticker|strategy|strike).
# These are the user's ACTUAL choices — the missing half of the feedback loop,
# which until now lived only in the PWA's localStorage and was invisible to the
# engine. We read them here via firebase-admin so signal_feedback can grade what
# the user did, not just what the scanner emitted.

_FIREBASE_ENV_KEY = "FIREBASE_SERVICE_ACCOUNT_JSON"


def _decisions_db() -> Optional[Any]:
    """Return an initialized Firestore client, or None when inert.

    Inert path (no log noise beyond one info line): `FIREBASE_SERVICE_ACCOUNT_JSON`
    unset → return None, so the whole decisions-read is a clean no-op. This is the
    SAME inert-without-key pattern as scripts/mirror_to_firestore._db() and the
    project's gmail_client / news_aggregator credentials — committing this changes
    nothing until the service-account JSON is present in the environment.

    With the key present, init firebase-admin from the service-account JSON and
    return a Firestore client. firebase-admin is imported lazily so this module
    (and its tests) import cleanly without the package installed.
    """
    sa_json = os.environ.get(_FIREBASE_ENV_KEY)
    if not sa_json:
        logger.info("%s unset — decisions read-back is inert (no-op)", _FIREBASE_ENV_KEY)
        return None

    import firebase_admin
    from firebase_admin import credentials, firestore

    info = json.loads(sa_json)
    cred = credentials.Certificate(info)
    # Guard against re-init if something already initialized the default app
    # (e.g. mirror_to_firestore ran in the same process).
    try:
        app = firebase_admin.get_app()
    except ValueError:
        app = firebase_admin.initialize_app(cred)
    return firestore.client(app)


def read_user_decisions(db: Optional[Any] = None) -> dict[str, dict]:
    """Read the `decisions` Firestore collection → {decision_key: decision_doc}.

    Returns an EMPTY dict when inert (no service-account key) or on any read
    error — never raises, so an unavailable Firestore can't break the Sheet-based
    grading. Each value is the decision doc the PWA wrote, shape roughly:
        { key, status (filled|killed|deferred), ticker, strategy, account,
          strike?, ts, user?, note?, fillPrice?, qty?, updatedAt }

    Pass `db` to inject a (mock) client in tests; otherwise it builds one via
    `_decisions_db()` (inert without the key).
    """
    if db is None:
        db = _decisions_db()
    if db is None:
        return {}

    out: dict[str, dict] = {}
    try:
        for snap in db.collection("decisions").stream():
            data = snap.to_dict() or {}
            key = str(data.get("key") or getattr(snap, "id", "") or "")
            if key:
                out[key] = data
    except Exception as e:  # noqa: BLE001 — best-effort; never fatal
        logger.warning("decisions read-back failed: %s", e)
        return {}
    return out


# ── Price fetching ─────────────────────────────────────────────────────────

def _fetch_prices(ticker: str, start: datetime, end: datetime) -> dict | None:
    """Fetch OHLCV from yfinance. Returns dict keyed by date string."""
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=5)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        # Flatten MultiIndex columns if present
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)
        out = {}
        for idx, row in df.iterrows():
            d = idx.strftime("%Y-%m-%d")
            out[d] = {
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0)),
            }
        return out
    except Exception as e:
        logger.warning(f"yfinance error for {ticker}: {e}")
        return None


def _get_price_at(prices: dict, target_date: datetime, window: int = 5) -> float | None:
    """Get closing price at or near target_date (±window business days)."""
    for delta in range(0, window + 1):
        for sign in [0, 1, -1]:
            d = (target_date + timedelta(days=delta * sign)).strftime("%Y-%m-%d")
            if d in prices:
                return prices[d]["close"]
    return None


def _get_indicators_at(ticker: str, scan_date: datetime) -> dict | None:
    """Fetch 120 days of OHLCV up to scan_date, run compute_indicators."""
    start = scan_date - timedelta(days=180)
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(scan_date + timedelta(days=2)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty or len(df) < 30:
            return None
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)
        # Trim to scan_date
        df = df[df.index <= scan_date.strftime("%Y-%m-%d")]
        if len(df) < 30:
            return None
        indicators = compute_indicators(df)
        return indicators
    except Exception as e:
        logger.warning(f"Indicator computation failed for {ticker} @ {scan_date}: {type(e).__name__}: {e}")
        return None


# ── Outcome evaluation ─────────────────────────────────────────────────────

def _label_by_pnl(pnl_pct: float) -> str:
    """WIN / LOSS / SCRATCH from the SIGN of premium-inclusive P&L.

    Labelling by P&L sign (not by whether the option was assigned) is what stops
    strategy_outcome and outcome_pnl_pct from ever contradicting each other: a
    covered call called away above cost is a WIN (its max-profit outcome), while a
    sideways-down CC whose drop exceeds the premium is a LOSS even though the call
    expired worthless. Breakeven (|pnl| < eps) is SCRATCH, excluded from win-rate.
    """
    if pnl_pct > PNL_SCRATCH_EPS:
        return "WIN"
    if pnl_pct < -PNL_SCRATCH_EPS:
        return "LOSS"
    return "SCRATCH"


def _eval_csp_outcome(
    strike: float, premium: float, price_at_eval: float,
) -> tuple[str, float]:
    """Evaluate a cash-secured put as realized, premium-inclusive P&L.

    outcome_pnl_pct = % of the cash-secured strike: keep the credit if the put
    expires OTM, else the credit minus the assignment loss. WIN/LOSS/SCRATCH by
    the SIGN of that P&L. Settlement logic is shared with backtest_scoring via
    src/option_pnl.csp_settle_pct — one P&L model across the system.
    """
    pnl_pct = csp_settle_pct(strike, premium, price_at_eval)
    return _label_by_pnl(pnl_pct), round(pnl_pct, 2)


def _eval_cc_outcome(
    strike: float, price_at_scan: float, price_at_eval: float, premium: float,
) -> tuple[str, float]:
    """Evaluate a covered call as realized, premium-inclusive P&L.

    outcome_pnl_pct = % of the share cost basis (price_at_scan): the stock move
    capped at the strike when called away, PLUS the premium the old stock-return
    proxy omitted. This fixes the two inversions the proxy produced — a profitable
    sideways-down CC the proxy logged NEGATIVE, and a called-away OTM call the proxy
    logged as "LOSS" with POSITIVE return. Shared with backtest_scoring via
    src/option_pnl.cc_settle_pct.
    """
    pnl_pct = cc_settle_pct(price_at_scan, strike, premium, price_at_eval)
    return _label_by_pnl(pnl_pct), round(pnl_pct, 2)


def _eval_buy_outcome(
    price_at_scan: float, price_at_eval: float,
) -> tuple[str, float]:
    """Evaluate BUY outcome — simple forward return."""
    if price_at_scan <= 0:
        return "SCRATCH", 0.0
    fwd_ret = (price_at_eval / price_at_scan - 1) * 100
    if fwd_ret > 1.0:
        return "WIN", round(fwd_ret, 2)
    elif fwd_ret < -1.0:
        return "LOSS", round(fwd_ret, 2)
    else:
        return "SCRATCH", round(fwd_ret, 2)


# ── Main pipeline ──────────────────────────────────────────────────────────

def run(*, dry: bool = False, lookback_days: int = 90, force: bool = False):
    logger.info("── Signal Feedback Loop ──")
    client = sh.authenticate()

    # 1. Read scan_results
    scan_rows = _read_tab(client, S.ScanResultRow.TAB_NAME)
    logger.info(f"Read {len(scan_rows)} rows from scan_results")

    # 1b. Read the user's REAL fill/kill/defer decisions from Firestore (the
    # write-back / feedback loop). ADDITIONAL input — does NOT replace or alter
    # the Sheet-based grading below. Empty dict when inert (no service-account
    # key) or on any read error, so this can never break the existing pipeline.
    user_decisions = read_user_decisions()
    if user_decisions:
        logger.info(f"Read {len(user_decisions)} real user decisions from Firestore")

    # 2. Read existing signal_outcomes to avoid re-processing
    # Read the full graded history once: its keys drive dedup (unless --force
    # re-evaluates everything) AND it is the JOIN target for selection grading.
    historical_outcomes = _read_tab(client, S.SignalOutcomeRow.TAB_NAME)
    existing_outcomes = set()
    if not force:
        for o in historical_outcomes:
            key = (o.get("scan_date", "")[:10], o.get("ticker", ""),
                   o.get("strategy", ""), o.get("strike", ""), o.get("expiry", ""))
            existing_outcomes.add(key)
        logger.info(f"Found {len(existing_outcomes)} existing outcomes (skipping)")

    # 3. Filter to mature picks
    now = datetime.now()
    cutoff_earliest = now - timedelta(days=lookback_days)
    candidates = []

    for r in scan_rows:
        scan_dt = _parse_date(r.get("date", ""))
        if not scan_dt:
            continue
        if scan_dt < cutoff_earliest:
            continue

        ticker = r.get("ticker", "").strip()
        strategy = r.get("strategy", "").strip().upper()
        strike = _parse_float(r.get("strike", ""))
        expiry = r.get("expiry", "").strip()
        dte = int(_parse_float(r.get("dte", "")))

        if not ticker or not strategy:
            continue

        # Determine evaluation date
        if strategy in ("CSP", "CC", "LONG_CALL", "LONG_PUT") and expiry:
            # Evaluate at expiry
            try:
                eval_dt = datetime.strptime(expiry[:8], "%Y%m%d")
            except ValueError:
                try:
                    eval_dt = datetime.strptime(expiry[:10], "%Y-%m-%d")
                except ValueError:
                    eval_dt = scan_dt + timedelta(days=max(dte, BUY_EVAL_DAYS))
        else:
            # BUY or unknown — evaluate at +30d
            eval_dt = scan_dt + timedelta(days=BUY_EVAL_DAYS)

        # Must be past evaluation date
        if eval_dt > now - timedelta(days=MIN_EVAL_DAYS):
            continue

        # Check dedup
        key = (scan_dt.strftime("%Y-%m-%d"), ticker, strategy,
               f"{strike:.2f}", expiry)
        if key in existing_outcomes:
            continue

        candidates.append({
            "scan_dt": scan_dt,
            "eval_dt": eval_dt,
            "ticker": ticker,
            "strategy": strategy,
            "strike": strike,
            "expiry": expiry,
            "dte": dte,
            "price_at_scan": _parse_float(r.get("underlying_last", "")),
            "composite_score": _parse_float(r.get("composite_score", "")),
            "technical_score": _parse_float(r.get("technical_score", "")),
            "premium": _parse_float(r.get("premium", "")),
            "cash_required": _parse_float(r.get("cash_required", "")),
            "breakeven": _parse_float(r.get("breakeven", "")),
            "signals_json": r.get("signals_json", ""),
        })

    logger.info(f"Found {len(candidates)} mature picks to evaluate")

    if not candidates:
        logger.info("No new picks to evaluate — done")
        return

    # 4. Group by ticker to minimize yfinance calls
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_ticker[c["ticker"]].append(c)

    # 5. Process each ticker
    new_outcomes: list[S.SignalOutcomeRow] = []
    stats = {"win": 0, "loss": 0, "scratch": 0, "error": 0}
    signal_hits: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for ticker, picks in by_ticker.items():
        logger.info(f"Processing {ticker} ({len(picks)} picks)")

        # Find date range needed
        earliest_scan = min(p["scan_dt"] for p in picks)
        latest_eval = max(p["eval_dt"] for p in picks)

        # Fetch price data (scan_date - 180d to latest_eval + 5d)
        prices = _fetch_prices(
            ticker,
            start=earliest_scan - timedelta(days=180),
            end=latest_eval + timedelta(days=5),
        )
        if not prices:
            logger.warning(f"No price data for {ticker} — skipping {len(picks)} picks")
            stats["error"] += len(picks)
            continue

        time.sleep(YF_DELAY_S)

        for pick in picks:
            # Get price at evaluation date
            price_at_eval = _get_price_at(prices, pick["eval_dt"])
            if price_at_eval is None:
                logger.warning(f"No eval price for {ticker} @ {pick['eval_dt'].date()}")
                stats["error"] += 1
                continue

            price_at_scan = pick["price_at_scan"]
            if price_at_scan <= 0:
                # Try to get from yfinance
                price_at_scan = _get_price_at(prices, pick["scan_dt"]) or 0
            if price_at_scan <= 0:
                stats["error"] += 1
                continue

            # Compute forward return
            fwd_ret = (price_at_eval / price_at_scan - 1) * 100

            # Strategy-specific outcome
            strategy = pick["strategy"]
            if strategy == "CSP":
                outcome, pnl_pct = _eval_csp_outcome(
                    pick["strike"], pick["premium"], price_at_eval,
                )
            elif strategy == "CC":
                outcome, pnl_pct = _eval_cc_outcome(
                    pick["strike"], price_at_scan, price_at_eval, pick["premium"],
                )
            elif strategy in ("LONG_CALL", "LONG_PUT"):
                # Simplified: LONG_CALL wins if price > strike, LONG_PUT if price < strike
                if strategy == "LONG_CALL":
                    outcome, pnl_pct = _eval_buy_outcome(price_at_scan, price_at_eval)
                else:
                    # Invert for puts
                    o, p = _eval_buy_outcome(price_at_scan, price_at_eval)
                    outcome = {"WIN": "LOSS", "LOSS": "WIN", "SCRATCH": "SCRATCH"}[o]
                    pnl_pct = -p
            else:
                # BUY or anything else — simple forward return
                outcome, pnl_pct = _eval_buy_outcome(price_at_scan, price_at_eval)

            stats[outcome.lower()] = stats.get(outcome.lower(), 0) + 1

            # Signals at scan time. Prefer the exact snapshot persisted by the
            # scanner (includes the IV-dependent iv_rv_ratio / term_structure
            # that can't be reconstructed from price-only history). Fall back to
            # reconstruction for older rows written before signals_json existed.
            signals = None
            snap = pick.get("signals_json", "")
            if snap:
                try:
                    parsed = json.loads(snap)
                    if isinstance(parsed, dict) and parsed:
                        signals = {k: float(v) for k, v in parsed.items()}
                except Exception:
                    signals = None
            if signals is None:
                indicators = _get_indicators_at(ticker, pick["scan_dt"])
                if indicators:
                    signals = compute_signals(indicators)
                else:
                    signals = {k: 0.0 for k in [
                        "rsi", "macd", "macd_cross", "bb_pct_b", "bb_squeeze",
                        "wvf", "trend", "momentum", "volume_spike", "divergence",
                        "candle", "fib_support", "volatility", "vol_regime",
                        "iv_rv_ratio", "term_structure",
                    ]}

            time.sleep(YF_DELAY_S)

            # Build outcome row
            row = S.SignalOutcomeRow(
                scan_date=pick["scan_dt"].strftime("%Y-%m-%d"),
                eval_date=pick["eval_dt"].strftime("%Y-%m-%d"),
                ticker=ticker,
                strategy=strategy,
                scan_composite=pick["composite_score"],
                scan_technical=pick["technical_score"],
                strike=pick["strike"],
                expiry=pick["expiry"],
                dte=pick["dte"],
                price_at_scan=price_at_scan,
                price_at_eval=price_at_eval,
                fwd_return_pct=round(fwd_ret, 2),
                strategy_outcome=outcome,
                outcome_pnl_pct=pnl_pct,
                pnl_model=S.PNL_MODEL_PREMIUM,
                sig_rsi=signals.get("rsi", 0),
                sig_macd=signals.get("macd", 0),
                sig_macd_cross=signals.get("macd_cross", 0),
                sig_bb_pct_b=signals.get("bb_pct_b", 0),
                sig_bb_squeeze=signals.get("bb_squeeze", 0),
                sig_wvf=signals.get("wvf", 0),
                sig_trend=signals.get("trend", 0),
                sig_momentum=signals.get("momentum", 0),
                sig_volume_spike=signals.get("volume_spike", 0),
                sig_divergence=signals.get("divergence", 0),
                sig_candle=signals.get("candle", 0),
                sig_fib_support=signals.get("fib_support", 0),
                sig_volatility=signals.get("volatility", 0),
                sig_vol_regime=signals.get("vol_regime", 0),
                sig_iv_rv_ratio=signals.get("iv_rv_ratio", 0),
                sig_term_structure=signals.get("term_structure", 0),
            )
            new_outcomes.append(row)

            # Track signal-outcome correlation data
            for sig_name, sig_val in signals.items():
                signal_hits[f"{strategy}:{sig_name}"].append((sig_val, pnl_pct))

    logger.info(f"Evaluated {len(new_outcomes)} picks: "
                f"{stats['win']} WIN, {stats['loss']} LOSS, "
                f"{stats['scratch']} SCRATCH, {stats['error']} errors")

    if not new_outcomes:
        logger.info("No outcomes to write")
        return

    # 6. Write to sheet
    if dry:
        logger.info(f"[DRY] Would write {len(new_outcomes)} rows to signal_outcomes")
        for o in new_outcomes[:5]:
            logger.info(f"  {o.ticker} {o.strategy} {o.scan_date} → {o.strategy_outcome} ({o.outcome_pnl_pct:+.1f}%)")
    else:
        sh.ensure_headers(client, S.SignalOutcomeRow.TAB_NAME, S.SignalOutcomeRow.HEADERS)
        outcome_rows = [o.to_row() for o in new_outcomes]
        sh.append_rows(client, S.SignalOutcomeRow.TAB_NAME, outcome_rows)
        logger.info(f"✓ Wrote {len(outcome_rows)} rows to signal_outcomes")

    # 7. Compute signal accuracy report (carries the real-user-decisions section
    #    + selection grade, JOINing decisions onto the full graded history).
    graded_outcomes = _normalize_outcomes(historical_outcomes, new_outcomes)
    report = _build_report(new_outcomes, signal_hits, stats,
                           user_decisions=user_decisions,
                           graded_outcomes=graded_outcomes)

    # 8. Send Telegram summary
    if not dry:
        _send_telegram(report)
    else:
        logger.info(f"[DRY] Telegram report:\n{report}")


# ── Selection-skill grading (the user-decisions feedback loop) ──────────────

def _decision_date(key: str, doc: dict) -> datetime | None:
    """Best-effort date a decision was made.

    Prefer the date embedded in the decision key (``date|account|ticker|
    strategy|strike`` — the same compound key the PWA and push_decisions.py
    write), then fall back to the ``ts`` / ``updatedAt`` fields (firebase-admin
    hands these back as datetimes, but tolerate epoch ms/s and ISO strings too).
    Returns None when nothing parses — the caller then matches on identity alone.
    """
    parts = str(key).split("|")
    if parts and parts[0]:
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(parts[0][:10], fmt)
            except ValueError:
                pass
    for field in ("ts", "updatedAt"):
        v = doc.get(field)
        if v in (None, ""):
            continue
        if isinstance(v, datetime):
            return v.replace(tzinfo=None)
        try:  # epoch seconds or milliseconds
            n = float(v)
            return datetime.fromtimestamp(n / 1000.0 if n > 1e12 else n)
        except (TypeError, ValueError, OSError, OverflowError):
            pass
        try:  # ISO-8601 string
            return datetime.fromisoformat(str(v).replace("Z", "").split("+")[0].strip())
        except ValueError:
            pass
    return None


def _decision_fields(key: str, doc: dict) -> tuple[str, str, float, str, datetime | None]:
    """Extract (ticker, strategy, strike, status, date) from a decision.

    Explicit doc fields win; the compound key is the fallback for each. ``status``
    accepts the PWA's ``status`` or ``action`` spelling (filled|killed|deferred).
    """
    parts = str(key).split("|")
    ticker = str(doc.get("ticker") or (parts[2] if len(parts) > 2 else "")).upper().strip()
    strategy = str(doc.get("strategy") or (parts[3] if len(parts) > 3 else "")).upper().strip()
    raw_strike = doc.get("strike")
    if raw_strike in (None, ""):
        raw_strike = parts[4] if len(parts) > 4 else 0
    try:
        strike = round(float(raw_strike), 2)
    except (TypeError, ValueError):
        strike = 0.0
    status = str(doc.get("status") or doc.get("action") or "").lower().strip()
    return ticker, strategy, strike, status, _decision_date(key, doc)


def _normalize_outcomes(
    historical_rows: list[dict] | None,
    new_rows: list[S.SignalOutcomeRow] | None,
) -> list[dict]:
    """Flatten historical sheet rows + this run's new outcomes into one graded
    list of ``{scan_date, ticker, strategy, strike, outcome}``, de-duplicated on
    the compound (scan_date, ticker, strategy, strike) key so a pick re-evaluated
    under --force is never counted twice."""
    norm: list[dict] = []
    seen: set[tuple] = set()

    def _add(scan_date, ticker, strategy, strike, outcome) -> None:
        sd = str(scan_date or "")[:10]
        tk = str(ticker or "").upper().strip()
        st = str(strategy or "").upper().strip()
        try:
            sk = round(float(strike or 0), 2)
        except (TypeError, ValueError):
            sk = 0.0
        oc = str(outcome or "").upper().strip()
        if not tk or not oc:
            return
        k = (sd, tk, st, f"{sk:.2f}")
        if k in seen:
            return
        seen.add(k)
        norm.append({"scan_date": sd, "ticker": tk, "strategy": st,
                     "strike": sk, "outcome": oc})

    for o in (historical_rows or []):
        _add(o.get("scan_date"), o.get("ticker"), o.get("strategy"),
             o.get("strike"), o.get("strategy_outcome"))
    for o in (new_rows or []):
        _add(o.scan_date, o.ticker, o.strategy, o.strike, o.strategy_outcome)
    return norm


def _grade_selection_skill(
    user_decisions: dict[str, dict],
    outcomes: list[dict],
    *,
    window_days: int = SELECTION_MATCH_WINDOW_DAYS,
    min_graded: int = SELECTION_MIN_GRADED,
) -> dict | None:
    """Grade the user's SELECTION skill — does discretion beat the raw engine?

    JOINs each real fill/kill/defer decision onto a graded pick (ticker+strategy,
    strike within $0.01, scan date within ``window_days``; nearest scan date wins)
    and asks: of the picks that went on to WIN, how often did the user FILL — and
    of the ones that went on to LOSE, how often did they fill anyway?

    The headline metric is::

        selection_edge = P(fill | WIN) − P(fill | LOSS)     # range −1 … +1

    +1 is perfect discrimination (took every winner, skipped every loser); 0 is
    no skill (fills winners and losers alike); negative means the discretion is
    actively anti-selective and the engine should be trusted over it. Only clean
    WIN/LOSS outcomes are graded — SCRATCHes carry no directional signal.

    Returns None (metric suppressed) when fewer than ``min_graded`` WIN/LOSS pairs
    match, or when either bucket is empty (the edge is undefined). Otherwise a
    dict: ``{n, n_win, n_loss, fill_rate_on_winners, fill_rate_on_losers,
    kill_rate_on_losers, selection_edge}``.
    """
    if not user_decisions or not outcomes:
        return None

    index: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for o in outcomes:
        if o["outcome"] not in ("WIN", "LOSS"):
            continue
        index[(o["ticker"], o["strategy"])].append(
            (_parse_date(o["scan_date"]), o["strike"], o["outcome"]))

    n_win = n_loss = fill_win = fill_loss = kill_loss = 0
    for key, doc in user_decisions.items():
        ticker, strategy, strike, status, ddate = _decision_fields(key, doc)
        if not ticker or not status:
            continue
        best_outcome, best_gap = None, None
        for sd, sk, oc in index.get((ticker, strategy), []):
            if abs(sk - strike) > 0.01 and not (sk == 0 and strike == 0):
                continue
            if sd and ddate:
                gap = abs((sd - ddate).days)
                if gap > window_days:
                    continue
            else:
                gap = 0
            if best_gap is None or gap < best_gap:
                best_outcome, best_gap = oc, gap
        if best_outcome is None:
            continue
        filled = status == "filled"
        if best_outcome == "WIN":
            n_win += 1
            fill_win += filled
        else:  # LOSS
            n_loss += 1
            fill_loss += filled
            kill_loss += status == "killed"

    n = n_win + n_loss
    if n < min_graded or n_win == 0 or n_loss == 0:
        return None
    frw = fill_win / n_win
    frl = fill_loss / n_loss
    return {
        "n": n, "n_win": n_win, "n_loss": n_loss,
        "fill_rate_on_winners": frw,
        "fill_rate_on_losers": frl,
        "kill_rate_on_losers": kill_loss / n_loss,
        "selection_edge": frw - frl,
    }


# ── Real-user-decisions summary (feedback loop) ─────────────────────────────

def _summarize_user_decisions(
    user_decisions: dict[str, dict],
    grade: dict | None = None,
) -> str:
    """Render the report section for the user's REAL fill/kill/defer choices.

    `user_decisions` is the {decision_key: doc} map from read_user_decisions().
    Returns "" when empty (inert / no decisions) so the section vanishes cleanly.

    Two halves of the feedback loop:
      • EXPOSURE — a fill/kill/defer count of what the user actually did (vs the
        scanner-pick grading above, which measures what the engine PROPOSED).
      • SKILL — when `grade` (from _grade_selection_skill) is supplied, the
        selection edge: does the user fill the picks that go on to WIN and skip
        the ones that go on to LOSE? Suppressed upstream when the matched sample
        is too small, so a present `grade` is always reportable.

    This section is purely additive — it never alters the Sheet-derived win-rate
    or signal calibration.
    """
    if not user_decisions:
        return ""
    by_status: dict[str, int] = defaultdict(int)
    for doc in user_decisions.values():
        status = str(doc.get("status") or doc.get("action") or "unknown").lower()
        by_status[status] += 1
    parts = [f"{by_status[s]} {s}" for s in sorted(by_status)]
    lines = [
        f"🧑 Real user decisions: {len(user_decisions)} recorded "
        f"({', '.join(parts)})"
    ]
    if grade:
        edge = grade["selection_edge"]
        if edge >= 0.15:
            verdict = "your discretion ADDS value over the raw engine"
        elif edge <= -0.15:
            verdict = "your discretion is ANTI-selective — lean on the engine"
        else:
            verdict = "discretion ≈ neutral vs the engine"
        lines.append(f"🎯 Selection edge: {edge:+.2f} — {verdict}")
        lines.append(
            f"   fills winners {grade['fill_rate_on_winners'] * 100:.0f}% vs "
            f"losers {grade['fill_rate_on_losers'] * 100:.0f}% · "
            f"kills losers {grade['kill_rate_on_losers'] * 100:.0f}% · "
            f"graded {grade['n']} ({grade['n_win']}W/{grade['n_loss']}L)"
        )
    return "\n".join(lines)


# ── Signal accuracy analysis ──────────────────────────────────────────────

def _build_report(
    outcomes: list[S.SignalOutcomeRow],
    signal_hits: dict[str, list[tuple[float, float]]],
    stats: dict,
    user_decisions: dict[str, dict] | None = None,
    graded_outcomes: list[dict] | None = None,
) -> str:
    """Build a text report of signal accuracy findings.

    `user_decisions` (optional) is the real fill/kill/defer choices from
    read_user_decisions(); when present a summary section is appended.
    `graded_outcomes` (optional) is the normalized WIN/LOSS history from
    _normalize_outcomes(); with both present, the section also carries the
    selection-skill edge. Either way the section is purely additive — it never
    alters the Sheet-derived win-rate / calibration.
    """
    grade = (_grade_selection_skill(user_decisions, graded_outcomes)
             if user_decisions and graded_outcomes else None)
    decisions_section = _summarize_user_decisions(user_decisions or {}, grade)

    total = stats.get("win", 0) + stats.get("loss", 0) + stats.get("scratch", 0)
    if total == 0:
        base = "No outcomes to report."
        return f"{base}\n\n{decisions_section}" if decisions_section else base

    win_rate = stats["win"] / total * 100
    avg_pnl = sum(o.outcome_pnl_pct for o in outcomes) / len(outcomes)

    lines = [
        "📊 Signal Feedback Report",
        f"Picks evaluated: {total}",
        f"Win rate: {win_rate:.0f}% ({stats['win']}W / {stats['loss']}L / {stats['scratch']}S)",
        f"Avg outcome: {avg_pnl:+.1f}%",
        "",
    ]

    # Per-strategy breakdown
    by_strat: dict[str, list] = defaultdict(list)
    for o in outcomes:
        by_strat[o.strategy].append(o)

    for strat, picks in sorted(by_strat.items()):
        wins = sum(1 for p in picks if p.strategy_outcome == "WIN")
        wr = wins / len(picks) * 100 if picks else 0
        avg = sum(p.outcome_pnl_pct for p in picks) / len(picks)
        lines.append(f"{strat}: {wr:.0f}% WR ({len(picks)} picks, avg {avg:+.1f}%)")

    # Signal correlation analysis (only if enough data)
    if len(outcomes) >= 15:
        lines.append("")
        lines.append("Signal alignment vs weights:")

        # For each strategy, compute signal-outcome correlations
        for strat in sorted(by_strat.keys()):
            if strat not in STRATEGY_WEIGHTS:
                continue
            strat_outcomes = by_strat[strat]
            if len(strat_outcomes) < 10:
                continue

            misaligned = []
            weights = STRATEGY_WEIGHTS[strat]

            for sig_name in weights:
                key = f"{strat}:{sig_name}"
                pairs = signal_hits.get(key, [])
                if len(pairs) < 10:
                    continue

                # Simple correlation: when signal is positive, is outcome positive?
                sig_vals = [p[0] for p in pairs]
                pnl_vals = [p[1] for p in pairs]
                mean_sig = sum(sig_vals) / len(sig_vals)
                mean_pnl = sum(pnl_vals) / len(pnl_vals)

                # Pearson correlation (simplified)
                cov = sum((s - mean_sig) * (p - mean_pnl) for s, p in pairs) / len(pairs)
                var_s = sum((s - mean_sig) ** 2 for s in sig_vals) / len(sig_vals)
                var_p = sum((p - mean_pnl) ** 2 for p in pnl_vals) / len(pnl_vals)

                if var_s > 0 and var_p > 0:
                    corr = cov / (var_s ** 0.5 * var_p ** 0.5)
                else:
                    corr = 0.0

                configured_weight = weights[sig_name]
                # Weight sign should match correlation sign
                weight_sign = 1 if configured_weight > 0 else (-1 if configured_weight < 0 else 0)
                corr_sign = 1 if corr > 0.1 else (-1 if corr < -0.1 else 0)

                if weight_sign != 0 and corr_sign != 0 and weight_sign != corr_sign:
                    misaligned.append((sig_name, configured_weight, corr))

            if misaligned:
                lines.append(f"\n⚠️ {strat} weight misalignments:")
                for sig, wt, corr in sorted(misaligned, key=lambda x: abs(x[2]), reverse=True)[:3]:
                    lines.append(f"  {sig}: weight={wt:+.0f} but corr={corr:+.2f}")
            else:
                lines.append(f"✅ {strat}: weights aligned with outcomes")

    # Sample size warning
    if total < 30:
        lines.append("")
        lines.append(f"⚠️ Small sample ({total} picks) — findings are directional, not conclusive.")
        lines.append(f"Need ≥50 picks per strategy for reliable weight calibration.")

    # Real-user-decisions section (feedback loop) — additive, never alters grading.
    if decisions_section:
        lines.append("")
        lines.append(decisions_section)

    return "\n".join(lines)


# ── Phase 2: empirical weight calibration ───────────────────────────────────
# The 16 signal columns in signal_outcomes map to STRATEGY_WEIGHTS keys by
# dropping the "sig_" prefix.
_SIG_COLS = [
    "sig_rsi", "sig_macd", "sig_macd_cross", "sig_bb_pct_b", "sig_bb_squeeze",
    "sig_wvf", "sig_trend", "sig_momentum", "sig_volume_spike", "sig_divergence",
    "sig_candle", "sig_fib_support", "sig_volatility", "sig_vol_regime",
    "sig_iv_rv_ratio", "sig_term_structure",
]
CALIB_MIN_PER_STRATEGY = 30   # rows needed before a strategy is calibrated
CALIB_NOISE_ABS_R = 0.05      # |corr| below this → signal is noise
CALIB_SIGNAL_ABS_R = 0.10     # |corr| at/above this → meaningful sign signal


def calibrate_weights(
    outcome_rows: list[dict],
    min_per_strategy: int = CALIB_MIN_PER_STRATEGY,
) -> dict:
    """
    Phase-2 empirical weight calibration. For each strategy with enough closed
    outcomes, regress realized P&L on the 16 scan-time signal values and compare
    the empirical importance of each signal to its configured STRATEGY_WEIGHTS.

    Per signal it reports:
      - corr   : univariate Pearson r vs outcome_pnl_pct (robust, primary)
      - beta   : multivariate OLS coefficient (joint, collinearity-prone)
      - verdict: confirmed | SIGN-FLIP | noise | weak
      - suggested: a proposed weight = current total |weight| budget redistributed
                   by |corr|, sign from corr. NOT applied — a proposal for review.
    Also reports OLS R² (does the composite explain ANY variance?).

    Pure: takes rows, returns a dict. Does NOT mutate STRATEGY_WEIGHTS.
    Returns {strategy: {n, r2, signals: [...], flips: [...], noise: [...]}}.
    """
    import numpy as np

    out: dict = {}
    by_strat: dict[str, list[dict]] = defaultdict(list)
    for r in outcome_rows or []:
        strat = str(r.get("strategy", "")).upper()
        if strat in STRATEGY_WEIGHTS:
            by_strat[strat].append(r)

    for strat, rows in by_strat.items():
        weights = STRATEGY_WEIGHTS[strat]
        # Build y and X from rows with a usable outcome + all signal values.
        ys: list[float] = []
        xs: list[list[float]] = []
        for r in rows:
            raw = r.get("outcome_pnl_pct", "")
            if raw is None or raw == "":   # missing — skip (do NOT treat 0.0 as missing)
                continue
            try:
                y = float(raw)
            except (TypeError, ValueError):
                continue
            if y != y:  # NaN
                continue
            try:
                xrow = [float(r.get(c, "") or 0.0) for c in _SIG_COLS]
            except (TypeError, ValueError):
                continue
            ys.append(y)
            xs.append(xrow)

        n = len(ys)
        if n < min_per_strategy:
            out[strat] = {"n": n, "r2": None, "signals": [], "flips": [],
                          "noise": [], "skipped": f"only {n} rows (<{min_per_strategy})"}
            continue

        Y = np.array(ys, dtype=float)
        X = np.array(xs, dtype=float)

        # Univariate Pearson r per signal (zero-variance → 0).
        corrs: dict[str, float] = {}
        for j, col in enumerate(_SIG_COLS):
            xj = X[:, j]
            if xj.std() < 1e-9 or Y.std() < 1e-9:
                corrs[col] = 0.0
            else:
                corrs[col] = float(np.corrcoef(xj, Y)[0, 1])

        # Multivariate OLS with intercept; R² for explanatory power.
        A = np.hstack([X, np.ones((n, 1))])
        beta, *_ = np.linalg.lstsq(A, Y, rcond=None)
        y_hat = A @ beta
        ss_res = float(((Y - y_hat) ** 2).sum())
        ss_tot = float(((Y - Y.mean()) ** 2).sum())
        r2 = (1 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

        # Suggested reweights: redistribute the current total |weight| budget by
        # |corr|, taking the sign from corr (the data's direction).
        total_abs = sum(abs(w) for w in weights.values()) or 1.0
        sum_abs_r = sum(abs(corrs[f"sig_{k}"]) for k in weights) or 1.0

        signals = []
        flips, noise = [], []
        for k in weights:
            col = f"sig_{k}"
            r = corrs.get(col, 0.0)
            b = float(beta[_SIG_COLS.index(col)])
            w = weights[k]
            w_sign = (w > 0) - (w < 0)
            r_sign = (r > CALIB_SIGNAL_ABS_R) - (r < -CALIB_SIGNAL_ABS_R)
            if abs(r) < CALIB_NOISE_ABS_R:
                verdict = "noise"
                noise.append(k)
            elif w_sign and r_sign and w_sign != r_sign:
                verdict = "SIGN-FLIP"
                flips.append(k)
            elif abs(r) >= CALIB_SIGNAL_ABS_R:
                verdict = "confirmed"
            else:
                verdict = "weak"
            suggested = round(total_abs * abs(r) / sum_abs_r, 1)
            if r < 0:
                suggested = -suggested
            signals.append({
                "signal": k, "weight": w, "corr": round(r, 3),
                "beta": round(b, 4), "verdict": verdict, "suggested": suggested,
            })
        signals.sort(key=lambda s: abs(s["corr"]), reverse=True)
        out[strat] = {"n": n, "r2": round(r2, 4), "signals": signals,
                      "flips": flips, "noise": noise, "skipped": None}

    return out


def format_calibration_report(results: dict) -> str:
    """Render calibrate_weights() output as a concise text report."""
    lines = ["🔬 Phase-2 Weight Calibration",
             "(empirical betas vs configured weights — PROPOSALS, not applied)",
             "Note: CC outcome P&L is being corrected (premium-inclusive); treat",
             "CC results as provisional until that lands.", ""]
    if not results:
        return "No signal_outcomes data to calibrate."
    for strat in sorted(results):
        res = results[strat]
        if res.get("skipped"):
            lines.append(f"{strat}: skipped — {res['skipped']}")
            continue
        r2 = res["r2"]
        lines.append(f"━ {strat}  (n={res['n']}, OLS R²={r2:.3f})")
        if r2 is not None and r2 < 0.02:
            lines.append("  ⚠️ R²≈0 — signals jointly explain ~no variance (echoes the")
            lines.append("     backtest: selection edge is weak; lean on IV/RV + term structure).")
        if res["flips"]:
            lines.append(f"  🔴 SIGN-FLIPS (weight points wrong way): {', '.join(res['flips'])}")
        if res["noise"]:
            lines.append(f"  ⚪ noise (|corr|<{CALIB_NOISE_ABS_R}): {', '.join(res['noise'])}")
        # Top 5 by |corr|
        lines.append("  signal            weight  corr   →suggest  verdict")
        for s in res["signals"][:6]:
            lines.append(
                f"  {s['signal']:<16}{s['weight']:>+5.0f}  {s['corr']:>+5.2f}"
                f"  {s['suggested']:>+6.1f}  {s['verdict']}"
            )
        lines.append("")
    return "\n".join(lines)


# ── Telegram ───────────────────────────────────────────────────────────────

def _send_telegram(report: str):
    """Send feedback report to Telegram."""
    try:
        from src.telegram import send, OPTIONS_INTEL_TOPIC
        # Use the options intel topic (closest fit for quantitative signals)
        send(report, message_thread_id=OPTIONS_INTEL_TOPIC)
        logger.info("✓ Sent Telegram report")
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


# ── CLI ────────────────────────────────────────────────────────────────────

def run_calibration(dry: bool = False) -> str:
    """Phase-2 standalone: read the full signal_outcomes history and report
    empirical weight calibration. Does NOT re-evaluate picks or mutate weights."""
    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    rows = _read_tab(client, S.SignalOutcomeRow.TAB_NAME)
    logger.info(f"Calibration: read {len(rows)} signal_outcomes rows")
    results = calibrate_weights(rows)
    report = format_calibration_report(results)
    if dry:
        logger.info(f"[DRY] Calibration report:\n{report}")
    else:
        logger.info(report)
        _send_telegram(report)
    return report


def main():
    ap = argparse.ArgumentParser(description="Signal Feedback Loop")
    ap.add_argument("--dry", action="store_true", help="Don't write to sheets or Telegram")
    ap.add_argument("--days", type=int, default=90, help="Lookback window in days")
    ap.add_argument("--force", action="store_true", help="Re-evaluate all picks (ignore existing outcomes)")
    ap.add_argument("--calibrate", action="store_true",
                    help="Phase-2: empirical weight calibration over full history (no re-eval)")
    args = ap.parse_args()

    if args.calibrate:
        run_calibration(dry=args.dry)
    else:
        run(dry=args.dry, lookback_days=args.days, force=args.force)


if __name__ == "__main__":
    main()
