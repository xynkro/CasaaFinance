#!/usr/bin/env python3
"""
risk_parity_recommend.py — Auto-generate specific BUY recommendations
from the latest risk_parity_audit + write to decision_queue with
source="risk_parity".

Layer 5 of the Risk Parity integration. Layers 1-4 (audit + targets +
PWA panel + brain hooks) produced an audit ("Caspar bond_long -15pp
underweight, $1,118 starter") but no actionable decision. This layer
closes the loop: per UNDERWEIGHT class, pick a canonical ticker,
size at 30% of rebalance_amount (capped at 5% NLV), compute entry/
stop/target, score conviction 1-5, and write to decision_queue.

For each UNDERWEIGHT asset_class (delta_pct < -5):
  1. Pick canonical ticker from CANONICAL_TICKER preference list,
     filtered to ones present in `prompts/watchlist.yaml`.
  2. Compute size:
       target_dollars = abs(rebalance_amount_usd) × 0.30  # 30% starter
       cap at 5% of account NLV
       qty = floor(target_dollars / current_price)
  3. Compute entry / stop / target:
       Entry = current_price (TV close, fallback to 0)
       Stop = entry × 0.95 (5%) for bonds, × 0.92 (8%) for shares
       Target = entry × 1.06 (6%) for bonds, × 1.12 (12%) for shares
  4. Compute conviction (1-5 integer):
       Base from |delta_pct|: >15→5, 10-15→4, 7-10→3, 5-7→2
       Modifiers (each ±1, clamped to 1-5):
         +1 if TV daily rec ∈ {BUY, STRONG_BUY}
         -1 if TV daily rec ∈ {SELL, STRONG_SELL}
         +1 if asset_class is defensive (bond_*/gold/vol_*) AND
           regime shows distribution_day SEVERE/HIGH or breadth < 50
         -1 if exposure_posture = CASH_PRIORITY AND class is equity_*
  5. Status from exposure_posture:
       NEW_ENTRY_ALLOWED → pending
       REDUCE_ONLY      → pending if defensive class else watching
       CASH_PRIORITY    → watching for everything except defensive
                          (defensive still pending — small starter hedge)
  6. Write DecisionRow with source="risk_parity" via the same
     idempotent compound-key upsert push_decisions uses.

Idempotent: today's source="risk_parity" rows are replaced on each
run via the (date_prefix, account, ticker, strategy, strike) key
that push_decisions implements.

Behavior:
  - --dry: print rows; no Sheet write
  - graceful skip on missing upstream data (regime/tv/exposure)
  - SGT-anchored timestamps via S.now_sgt_iso() (in DecisionRow.to_row())

Usage:
  python scripts/risk_parity_recommend.py            # live
  python scripts/risk_parity_recommend.py --dry      # print only

Cron:
  Tail-end of .github/workflows/risk-parity-audit.yml — runs after
  risk_parity_audit so the latest underweights drive fresh recs.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src import schema as S          # noqa: E402
from src import sheets as sh         # noqa: E402
from src.sync import load_env        # noqa: E402
from src.watchlist import (           # noqa: E402
    CANONICAL_ASSET_CLASSES,
    get_universe,
)


# --- ticker preference per asset_class -------------------------------------
# Per spec: pick the FIRST in this list that's present in watchlist.yaml;
# fall back to FIRST in the list if none of them surface.
CANONICAL_TICKER: dict[str, list[str]] = {
    "bond_long":          ["TLT", "EDV", "ZROZ"],
    "bond_intermediate":  ["IEF", "IEI", "BIV"],
    "gold":               ["GLDM", "GLD", "IAU"],
    "commodities_broad":  ["DBC", "USO"],
    "vol_long":           ["VIXM", "UVXY"],
    "equity_intl":        ["VEA", "EFA", "VXUS"],
    "equity_us_dividend": ["SCHD", "VYM", "DGRO"],
    # Rare to need a rebalance-up to broad US equity, but include for
    # completeness — first liquid option.
    "equity_us":          ["SPY", "VOO", "VTI"],
}

# bucket mapping for DecisionRow.bucket — collapses 8 asset_classes to
# the smaller bucket taxonomy the PWA Decisions tab + brain prompts use.
BUCKET_FOR_ASSET_CLASS: dict[str, str] = {
    "bond_long":          "bond",
    "bond_intermediate":  "bond",
    "gold":               "commodity",
    "commodities_broad":  "commodity",
    "vol_long":           "hedge",
    "equity_intl":        "core",
    "equity_us_dividend": "core",
    "equity_us":          "blue_chip",
}

# Defensive classes get the regime-distress conviction bump and stay
# `pending` even under CASH_PRIORITY — these are the ALLOWED hedges in
# a defensive regime.
DEFENSIVE_CLASSES = {"bond_long", "bond_intermediate", "gold", "vol_long"}

# Bond-class stop/target (lower vol → tighter envelope).
BOND_CLASSES = {"bond_long", "bond_intermediate"}


# --- helpers ---------------------------------------------------------------

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("risk_parity_recommend")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _to_float(v, default: float = 0.0) -> float:
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _read_latest_rows(client, tab_name: str, logger: logging.Logger) -> list[dict]:
    """
    Return all rows from the LATEST date in `tab_name` as list of dicts.
    Defensive: returns [] on any failure, never raises.
    """
    try:
        ws = sh._open_sheet(client).worksheet(tab_name)
        rows = ws.get_all_values()
    except Exception as e:
        logger.warning(f"  [read] {tab_name} failed: {e}")
        return []
    if len(rows) <= 1:
        return []
    headers = rows[0]
    last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
    if not last_date:
        return []
    out: list[dict] = []
    for r in rows[1:]:
        if not r or not (r[0] or "").startswith(last_date):
            continue
        out.append(dict(zip(headers, r)))
    return out


def _read_latest_audit_batch(client, logger: logging.Logger) -> list[dict]:
    """
    risk_parity_audit may have multiple batches per day (workflow re-runs).
    Pick the LATEST timestamp suffix and return only those 16 rows. Falls
    back to all-of-latest-date if timestamps are missing.
    """
    try:
        ws = sh._open_sheet(client).worksheet(S.RiskParityAuditRow.TAB_NAME)
        rows = ws.get_all_values()
    except Exception as e:
        logger.warning(f"  [read] risk_parity_audit failed: {e}")
        return []
    if len(rows) <= 1:
        return []
    headers = rows[0]
    last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
    if not last_date:
        return []
    today_rows = [r for r in rows[1:] if r and (r[0] or "").startswith(last_date)]
    if not today_rows:
        return []
    # Pick the latest timestamp (e.g. "2026-05-07T120317")
    last_ts = max((r[0] or "") for r in today_rows)
    # If the suffix structure is "<date>T<HHMMSS>", filter on exact match
    if "T" in last_ts:
        return [dict(zip(headers, r)) for r in today_rows if (r[0] or "") == last_ts]
    # No timestamps — return all of latest date
    return [dict(zip(headers, r)) for r in today_rows]


def _read_latest_snap_nlv(client, account: str, logger: logging.Logger) -> float:
    """Read latest snapshot_<account>.net_liq_<ccy>. 0.0 on failure."""
    rows = _read_latest_rows(client, f"snapshot_{account}", logger)
    if not rows:
        return 0.0
    rows.sort(key=lambda r: r.get("date", ""))
    field = "net_liq_usd" if account == "caspar" else "net_liq_sgd"
    return _to_float(rows[-1].get(field), 0.0)


def _read_latest_tv_daily(client, logger: logging.Logger) -> dict[str, dict]:
    """
    Return {ticker: tv_row_dict} for the LATEST date's daily-interval rows.
    Empty dict on failure.
    """
    rows = _read_latest_rows(client, "tv_signals", logger)
    out: dict[str, dict] = {}
    for r in rows:
        if (r.get("interval") or "").strip() != "1d":
            continue
        t = (r.get("ticker") or "").strip().upper()
        if t:
            out[t] = r
    return out


def _yfinance_price(ticker: str, logger: logging.Logger) -> float:
    """
    Fallback: pull last close from yfinance for tickers not in tv_signals
    (TLT, IEF, VEA, UVXY, etc.). Returns 0.0 on any failure — caller falls
    back to a placeholder rather than crash.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker)
        # Try fast_info first (much faster than .history()).
        try:
            p = float(info.fast_info["last_price"])
            if p > 0:
                return p
        except Exception:
            pass
        hist = info.history(period="5d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return 0.0
        # Last close
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"  [yfinance] {ticker} price fetch failed: {e}")
        return 0.0


def _resolve_price(
    ticker: str,
    tv_daily: dict[str, dict],
    yf_cache: dict[str, float],
    logger: logging.Logger,
) -> tuple[float, str]:
    """
    Resolve a ticker's price. Prefer tv_signals close; fall back to yfinance
    last close. Returns (price, recommendation_label). Empty rec if ticker
    has no TV row.
    """
    tv_row = tv_daily.get(ticker)
    if tv_row:
        price = _to_float(tv_row.get("close"), 0.0)
        rec = (tv_row.get("recommendation") or "").strip().upper()
        if price > 0:
            return price, rec
    # Fallback to yfinance with cache.
    if ticker not in yf_cache:
        yf_cache[ticker] = _yfinance_price(ticker, logger)
    return yf_cache[ticker], ""


def _read_latest_exposure(client, logger: logging.Logger) -> dict:
    """Return latest exposure_posture row; empty dict on failure."""
    rows = _read_latest_rows(client, "exposure_posture", logger)
    if not rows:
        return {}
    rows.sort(key=lambda r: r.get("date", ""))
    return rows[-1]


def _read_latest_regime(client, logger: logging.Logger) -> dict[str, dict]:
    """Return {source: regime_signals_row} for latest date. Empty on failure."""
    rows = _read_latest_rows(client, "regime_signals", logger)
    out: dict[str, dict] = {}
    for r in rows:
        s = (r.get("source") or "").strip()
        if s:
            out[s] = r
    return out


def _read_latest_usd_sgd(client, logger: logging.Logger) -> float:
    """Latest USD/SGD rate from `macro` tab. 1.0 fallback (caller handles
    Sarah specially — falling back to 1.0 just means we slightly over-state
    qty, which is preferable to crashing)."""
    rows = _read_latest_rows(client, "macro", logger)
    if not rows:
        return 1.0
    rows.sort(key=lambda r: r.get("date", ""))
    return _to_float(rows[-1].get("usd_sgd"), 1.0) or 1.0


# --- core logic ------------------------------------------------------------

def pick_ticker(asset_class: str, watchlist_tickers: set[str]) -> str:
    """
    Pick the canonical ticker for an asset_class. Prefer the FIRST in
    CANONICAL_TICKER[class] that is present in the user's watchlist.yaml;
    fall back to the FIRST in the preference list.
    """
    prefs = CANONICAL_TICKER.get(asset_class, [])
    if not prefs:
        return ""
    for t in prefs:
        if t in watchlist_tickers:
            return t
    return prefs[0]


def compute_size(
    rebalance_amount: float,
    nlv: float,
    price: float,
    fx_to_price_ccy: float = 1.0,
) -> tuple[int, float]:
    """
    Compute starter size: 30% of rebalance amount, capped at 5% of NLV,
    converted to shares via current price.

    Returns (qty_shares, target_dollars_account_ccy). target_dollars is
    in the account's NATIVE currency (USD for Caspar, SGD for Sarah)
    so the user-facing thesis matches the audit's units.

    `fx_to_price_ccy`: divisor to convert from account ccy → ticker
    quote ccy. For Caspar (USD account, USD-priced tickers): 1.0.
    For Sarah (SGD account, USD-priced tickers): usd_sgd.

    qty=0 if price unknown or below $0.01.
    """
    target_dollars = max(abs(rebalance_amount) * 0.30, 0.0)
    cap = max(nlv * 0.05, 0.0)
    target_dollars = min(target_dollars, cap)
    if price <= 0.01:
        return 0, target_dollars
    # Convert account-ccy budget → price ccy, then divide by price.
    budget_in_price_ccy = target_dollars / max(fx_to_price_ccy, 1e-9)
    qty = int(math.floor(budget_in_price_ccy / price))
    return qty, target_dollars


def base_conviction(delta_pct: float) -> int:
    """Map magnitude of underweight to base conviction 2-5."""
    mag = abs(delta_pct)
    if mag > 15:
        return 5
    if mag >= 10:
        return 4
    if mag >= 7:
        return 3
    return 2  # 5-7 range


def compute_conviction(
    delta_pct: float,
    asset_class: str,
    tv_recommendation: str,
    exposure_recommendation: str,
    regime: dict[str, dict],
) -> int:
    """
    Conviction 1-5 from base + modifiers. See module docstring for rules.
    """
    score = base_conviction(delta_pct)

    rec = (tv_recommendation or "").strip().upper()
    if rec in ("BUY", "STRONG_BUY"):
        score += 1
    elif rec in ("SELL", "STRONG_SELL"):
        score -= 1

    # Defensive class + regime distress → +1
    if asset_class in DEFENSIVE_CLASSES:
        dist_label = (regime.get("distribution_day", {}).get("label") or "").upper()
        breadth_score = _to_float(regime.get("market_breadth", {}).get("score"), 100.0)
        if dist_label in ("HIGH", "SEVERE") or breadth_score < 50:
            score += 1

    # CASH_PRIORITY + equity class → -1
    if exposure_recommendation == "CASH_PRIORITY" and asset_class.startswith("equity_"):
        score -= 1

    # Clamp to 1-5
    return max(1, min(5, score))


def compute_status(asset_class: str, exposure_recommendation: str) -> str:
    """
    Map exposure_posture.recommendation × asset_class to DecisionRow.status.

    NEW_ENTRY_ALLOWED → pending
    REDUCE_ONLY       → pending if defensive class else watching
    CASH_PRIORITY     → watching for everything except defensive (those
                        still pending — small starter hedge)
    Default          → pending (treat unknown like NEW_ENTRY_ALLOWED;
                       conservative bias to actually generate ideas).
    """
    rec = (exposure_recommendation or "").strip().upper()
    if rec == "NEW_ENTRY_ALLOWED":
        return "pending"
    if rec == "REDUCE_ONLY":
        return "pending" if asset_class in DEFENSIVE_CLASSES else "watching"
    if rec == "CASH_PRIORITY":
        return "pending" if asset_class in DEFENSIVE_CLASSES else "watching"
    return "pending"


def compute_entry_stop_target(
    asset_class: str,
    price: float,
) -> tuple[float, float, float]:
    """Return (entry, stop, target). Bonds get tighter envelope than shares."""
    entry = float(price) if price > 0 else 0.0
    if asset_class in BOND_CLASSES:
        stop = entry * 0.95
        target = entry * 1.06
    elif asset_class == "vol_long":
        # Vol products are extremely volatile — wider stop, modest upside.
        stop = entry * 0.85
        target = entry * 1.20
    else:
        stop = entry * 0.92
        target = entry * 1.12
    return entry, stop, target


def build_thesis(
    account: str,
    ticker: str,
    asset_class: str,
    delta_pct: float,
    rebalance_amount: float,
    target_dollars: float,
    qty: int,
    nlv: float,
    tv_recommendation: str,
    exposure_recommendation: str,
    regime: dict[str, dict],
    ccy: str,
) -> str:
    """Compose multi-sentence thesis string for DecisionRow.thesis."""
    parts: list[str] = []
    parts.append(
        f"Risk Parity audit row: {account} {asset_class} {delta_pct:+.1f}pp "
        f"(rebalance ~{rebalance_amount:,.0f} {ccy} to hit target). "
    )
    parts.append(
        f"This recommendation sizes a 30% starter (~{target_dollars:,.0f} {ccy}) "
        f"capped at 5% NLV, equating to {qty}sh of {ticker} at current price. "
    )
    if tv_recommendation:
        parts.append(f"TV daily consensus: {tv_recommendation}. ")
    else:
        parts.append("TV daily consensus: not available for this ticker. ")

    dist = (regime.get("distribution_day", {}).get("label") or "")
    breadth = (regime.get("market_breadth", {}).get("label") or "")
    macro = (regime.get("macro_regime", {}).get("label") or "")
    parts.append(
        f"Regime: distribution_day={dist or 'n/a'}, breadth={breadth or 'n/a'}, "
        f"macro={macro or 'n/a'}. "
    )

    parts.append(f"Exposure posture: {exposure_recommendation or 'unknown'}. ")

    if asset_class in DEFENSIVE_CLASSES:
        parts.append(
            "Defensive class — held to a non-zero floor for diversification "
            "hygiene; pending status is preserved even in CASH_PRIORITY since "
            "this is appropriate hedging for the regime, not new equity risk. "
        )
    else:
        parts.append(
            "Equity-side class — under CASH_PRIORITY this is a watching "
            "candidate; flips to pending when exposure posture loosens. "
        )

    parts.append(
        "Use this entry as the mechanical baseline; the WSR brain will "
        "validate or refine on the next run."
    )
    return "".join(parts)


# --- main ------------------------------------------------------------------

def build_recommendations(
    audit_rows: list[dict],
    nlv_by_account: dict[str, float],
    tv_daily: dict[str, dict],
    exposure: dict,
    regime: dict[str, dict],
    watchlist_tickers: set[str],
    usd_sgd: float,
    today: str,
    logger: logging.Logger,
) -> list[tuple[S.DecisionRow, str]]:
    """
    Build [(DecisionRow, asset_class), ...] from underweight audit rows.
    asset_class is returned alongside the row for clean dry-print display
    and regression-test reuse without re-parsing the thesis.
    """
    out: list[tuple[S.DecisionRow, str]] = []
    exposure_rec = (exposure.get("recommendation") or "").strip().upper()
    yf_cache: dict[str, float] = {}

    for r in audit_rows:
        if (r.get("rebalance_action") or "").strip().upper() != "UNDERWEIGHT":
            continue
        account = (r.get("account") or "").strip()
        asset_class = (r.get("asset_class") or "").strip()
        if account not in ("caspar", "sarah") or not asset_class:
            continue
        delta_pct = _to_float(r.get("delta_pct"))
        rebal_amt = _to_float(r.get("rebalance_amount_usd"))

        ticker = pick_ticker(asset_class, watchlist_tickers)
        if not ticker:
            logger.warning(f"  no ticker mapping for {asset_class} ({account}) — skip")
            continue

        # Resolve price — TV first, yfinance fallback for tickers (TLT/IEF/
        # VEA/UVXY/etc.) not covered by the daily TV pull.
        price, tv_rec = _resolve_price(ticker, tv_daily, yf_cache, logger)

        nlv = nlv_by_account.get(account, 0.0)
        ccy = "USD" if account == "caspar" else "SGD"
        # USD tickers priced in USD; Sarah's NLV is SGD. Convert budget→USD.
        # (SGX tickers C6L/G3B/ES3 are SGD-quoted but those don't appear
        # under our recommendation classes today.)
        fx = usd_sgd if account == "sarah" else 1.0

        qty, target_dollars = compute_size(rebal_amt, nlv, price, fx)
        entry, stop, target = compute_entry_stop_target(asset_class, price)
        conv = compute_conviction(delta_pct, asset_class, tv_rec, exposure_rec, regime)
        status = compute_status(asset_class, exposure_rec)

        bucket = BUCKET_FOR_ASSET_CLASS.get(asset_class, "core")
        thesis_1liner = (
            f"{ticker} BUY_DIP starter {qty}sh — RP rebalance: {asset_class} "
            f"{delta_pct:+.0f}pp underweight (target ~{target_dollars:,.0f} {ccy})"
        )
        thesis = build_thesis(
            account=account,
            ticker=ticker,
            asset_class=asset_class,
            delta_pct=delta_pct,
            rebalance_amount=rebal_amt,
            target_dollars=target_dollars,
            qty=qty,
            nlv=nlv,
            tv_recommendation=tv_rec,
            exposure_recommendation=exposure_rec,
            regime=regime,
            ccy=ccy,
        )

        row = S.DecisionRow(
            date=today,
            account=account,
            ticker=ticker,
            bucket=bucket,
            thesis_1liner=thesis_1liner,
            conv=int(conv),
            entry=entry,
            target=target,
            status=status,
            strategy="BUY_DIP",
            right="",
            strike=0.0,
            expiry="",
            premium_per_share=0.0,
            delta=0.0,
            annual_yield_pct=0.0,
            breakeven=stop,  # store the stop in the breakeven column for share entries
            cash_required=target_dollars,
            iv_rank=0.0,
            thesis_confidence=conv / 5.0,
            thesis=thesis,
            source="risk_parity",
        )
        out.append((row, asset_class))
    return out


def upsert_decisions(
    client, rows: list[S.DecisionRow], logger: logging.Logger,
) -> dict:
    """
    Idempotent upsert of source="risk_parity" rows, keyed by
    (date_prefix, account, ticker, strategy, strike) — same compound
    key as push_decisions. Replaces today's rp rows; preserves all
    other dates and other-source rows.
    """
    sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.DecisionRow.TAB_NAME)

    existing = ws.get_all_values()
    headers = existing[0] if existing else list(S.DecisionRow.HEADERS)

    new_rows: list[list[str]] = [r.to_row() for r in rows]
    new_keys: set[tuple] = set()
    for r in rows:
        new_keys.add(_decision_key(r.date, r.account, r.ticker, r.strategy, r.strike))

    keep_rows: list[list[str]] = [headers]
    dropped = 0
    for r in (existing[1:] if existing else []):
        if not r:
            continue
        row_date = (r[0] or "")[:10]
        row_account = r[1] if len(r) > 1 else ""
        row_ticker = r[2] if len(r) > 2 else ""
        row_strategy = r[9] if len(r) > 9 else ""
        row_strike_raw = r[11] if len(r) > 11 else ""
        if _decision_key(row_date, row_account, row_ticker, row_strategy, row_strike_raw) in new_keys:
            dropped += 1
            continue
        keep_rows.append(r)
    keep_rows.extend(new_rows)

    ws.clear()
    ws.update(values=keep_rows, range_name="A1", value_input_option="USER_ENTERED")
    return {"added": len(new_rows), "dropped": dropped}


def _decision_key(
    date_prefix: str,
    account: str,
    ticker: str,
    strategy: str,
    strike,
) -> tuple:
    """Mirror of push_decisions._decision_key — single source-of-truth shape."""
    try:
        strike_str = f"{float(strike):.2f}" if strike not in ("", None) else "0.00"
    except (TypeError, ValueError):
        strike_str = "0.00"
    return (date_prefix, account, ticker, strategy, strike_str)


def _print_dry(pairs: list[tuple[S.DecisionRow, str]]) -> None:
    """Compact table print for --dry runs. `pairs` is [(row, asset_class)]."""
    if not pairs:
        print("  (no UNDERWEIGHT classes — nothing to recommend)")
        return
    print(
        f"  {'account':8} {'ticker':6} {'class':22} {'qty':>4} "
        f"{'entry':>8} {'stop':>8} {'target':>8} {'conv':>4} {'status':9} thesis_1liner"
    )
    print(
        f"  {'-'*8} {'-'*6} {'-'*22} {'-'*4} {'-'*8} {'-'*8} {'-'*8} "
        f"{'-'*4} {'-'*9} {'-'*40}"
    )
    for r, cls in pairs:
        # qty is canonically encoded in the thesis_1liner ("starter Nsh —")
        # — extract it for display rather than re-deriving (FX makes the
        # cash_required/entry shortcut wrong for Sarah).
        qty_str = ""
        try:
            seg = r.thesis_1liner.split("starter ", 1)[1]
            qty_str = seg.split("sh", 1)[0]
        except Exception:
            qty_str = "?"
        print(
            f"  {r.account:8} {r.ticker:6} {cls:22} {qty_str:>4} "
            f"{r.entry:>8.2f} {r.breakeven:>8.2f} {r.target:>8.2f} {r.conv:>4} "
            f"{r.status:9} {r.thesis_1liner[:80]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="print recommendations only; no Sheet write")
    args = parser.parse_args()

    load_env()
    logger = setup_logger()

    today = S.now_sgt_date()
    logger.info(f"risk_parity_recommend start (date={today}, dry={args.dry})")

    try:
        client = sh.authenticate()
    except Exception as e:
        logger.error(f"sheets auth failed: {e}")
        return 2

    # --- read upstream sheets ---
    audit_rows = _read_latest_audit_batch(client, logger)
    if not audit_rows:
        logger.warning("no risk_parity_audit rows found — nothing to recommend")
        return 0

    nlv_by_account = {
        "caspar": _read_latest_snap_nlv(client, "caspar", logger),
        "sarah":  _read_latest_snap_nlv(client, "sarah", logger),
    }
    logger.info(f"  NLV: caspar={nlv_by_account['caspar']:,.0f} USD | "
                f"sarah={nlv_by_account['sarah']:,.0f} SGD")

    tv_daily = _read_latest_tv_daily(client, logger)
    logger.info(f"  tv_signals daily rows: {len(tv_daily)}")

    exposure = _read_latest_exposure(client, logger)
    logger.info(f"  exposure_posture: {exposure.get('recommendation') or 'n/a'}")

    regime = _read_latest_regime(client, logger)
    logger.info(f"  regime sources: {sorted(regime.keys())}")

    usd_sgd = _read_latest_usd_sgd(client, logger)
    logger.info(f"  usd_sgd: {usd_sgd:.4f}")

    # Watchlist tickers — used to filter ticker preference.
    try:
        universe = get_universe(client, logger)
        watchlist_tickers = set(t for ts in universe.values() for t in ts)
    except Exception as e:
        logger.warning(f"  watchlist load failed ({e}) — using preference defaults")
        watchlist_tickers = set()
    logger.info(f"  watchlist universe: {len(watchlist_tickers)} unique tickers")

    # --- build recommendations ---
    pairs = build_recommendations(
        audit_rows=audit_rows,
        nlv_by_account=nlv_by_account,
        tv_daily=tv_daily,
        exposure=exposure,
        regime=regime,
        watchlist_tickers=watchlist_tickers,
        usd_sgd=usd_sgd,
        today=today,
        logger=logger,
    )

    if not pairs:
        logger.info("no UNDERWEIGHT classes — nothing to recommend")
        if args.dry:
            _print_dry(pairs)
        return 0

    rows = [p[0] for p in pairs]

    # --- summary log ---
    by_bucket: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_bucket[r.bucket] += 1
        by_status[r.status] += 1
    bucket_str = ", ".join(f"{n} {b}" for b, n in sorted(by_bucket.items()))
    status_str = ", ".join(f"{n} {s}" for s, n in sorted(by_status.items()))
    logger.info(
        f"Generated {len(rows)} recommendations: {bucket_str} — {status_str}"
    )

    if args.dry:
        _print_dry(pairs)
        return 0

    # --- live write ---
    try:
        result = upsert_decisions(client, rows, logger)
    except Exception as e:
        logger.error(f"sheets upsert failed: {e}")
        return 2
    logger.info(
        f"upserted {result['added']} risk_parity rows "
        f"(dropped {result['dropped']} stale)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
