#!/usr/bin/env python3
"""
risk_parity_audit.py — Daily diversification hygiene check (Risk Parity LITE).

For each account (caspar, sarah):
  1. Read latest snapshot_* + positions_* + options.
  2. Map every holding to its asset_class via watchlist.get_asset_class().
  3. Compute capital allocation per asset class (mkt_val sums / NLV).
  4. Estimate vol per asset class (static lookup; tv_signals.atr is null).
  5. Compute risk_contribution_pct = capital_pct × vol_pct, normalize to 100%.
  6. Read target weights from config/risk_parity_targets.yaml.
  7. Compute delta_pct = capital_pct - target_pct.
  8. Classify:
       OVERWEIGHT   if delta_pct > 5
       UNDERWEIGHT  if delta_pct < -5
       ON_TARGET    otherwise
  9. Compute rebalance_amount = abs(delta_pct/100) × NLV (account-native ccy).
  10. Write one row per (account, asset_class) — 8 classes × 2 accounts = 16 rows.

This is NOT pure Risk Parity (30/40/15/7.5/7.5). The user trades wheel
strategies on equity-anchored capital — equity stays dominant (45-50%) but
bonds/gold/vol-long are held to a non-zero floor for diversification hygiene.

Behavior:
  - --dry / --dry-run : print all 16 rows; no Sheet write
  - account-native currency: Caspar=USD, Sarah=SGD (rebalance_amount column
    name is `rebalance_amount_usd` per schema convention; rationale text
    notes the actual currency for Sarah)
  - emits a row for every (account, asset_class) even if capital_pct=0 —
    the 0% rows surface UNDERWEIGHT recommendations (e.g. user's current
    0% bond allocation)
  - vol estimates come from a static lookup table indexed by asset_class.
    Spec called for tv_signals.atr/close as a proxy with this static table
    as fallback; current `tv_signals` schema has no `atr` column so the
    static table is the only source.
  - if the targets YAML is missing or malformed, we fall back to a built-in
    default that mirrors `config/risk_parity_targets.yaml` and log a warning.

Usage:
  python scripts/risk_parity_audit.py            # live — appends to sheet
  python scripts/risk_parity_audit.py --dry      # print only; no Sheet write

Cron:
  .github/workflows/risk-parity-audit.yml — daily 22:45 UTC Mon-Fri
  (after regime-signals 22:00 + tv-signals 22:30)
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src import schema as S          # noqa: E402
from src import sheets as sh         # noqa: E402
from src.sync import load_env        # noqa: E402
from src.watchlist import (           # noqa: E402
    CANONICAL_ASSET_CLASSES,
    get_asset_class,
)


# --- vol estimates by asset class (annualized %) ---------------------------
# Static lookup based on long-run historical vols — used because the current
# `tv_signals` schema has no atr column (spec listed it as a fallback path
# but we treat the static table as the primary signal until atr is added).
# Numbers are conservative midpoints from 10y-rolling realized vol on the
# representative ETFs in each class.
VOL_BY_CLASS: dict[str, float] = {
    "equity_us":           18.0,   # broad US equity (SPY-like)
    "equity_us_dividend":  14.0,   # dividend-anchored (SCHD)
    "equity_intl":         16.0,   # SGX-anchored
    "bond_long":           12.0,   # TLT/EDV — duration-driven vol
    "bond_intermediate":    5.0,   # IEF/AGG — much lower
    "gold":                15.0,   # GLD-like
    "commodities_broad":   22.0,   # broad commodities (DBC plus oil/silver)
    "vol_long":            85.0,   # UVXY/VIXM are extremely high vol by design
}


# --- targets loader --------------------------------------------------------

# GROWTH-TILTED, all-rounded (revamped 2026-05-30) — kept in sync with
# config/risk_parity_targets.yaml. Growth-dominant, capped protector (bonds
# leaned to IEF over TLT), real hedge sleeve. See the YAML header for rationale.
DEFAULT_TARGETS: dict[str, dict[str, float]] = {
    "caspar": {
        "equity_us": 64.0,
        "equity_us_dividend": 5.0,
        "equity_intl": 5.0,
        "bond_long": 6.0,            # TLT — capped (was 15): a rate bet, not protection
        "bond_intermediate": 7.0,    # IEF — the justified protector bond
        "gold": 5.0,
        "commodities_broad": 3.0,
        "vol_long": 5.0,
    },
    "sarah": {
        "equity_us": 46.0,
        "equity_us_dividend": 15.0,
        "equity_intl": 7.0,
        "bond_long": 8.0,            # capped (was 12)
        "bond_intermediate": 8.0,
        "gold": 6.0,
        "commodities_broad": 3.0,
        "vol_long": 7.0,
    },
}


def load_targets(logger: logging.Logger) -> dict[str, dict[str, float]]:
    """
    Load per-account targets from config/risk_parity_targets.yaml. Falls
    back to DEFAULT_TARGETS on any failure (logged at WARNING). Returned
    dict is always {account: {asset_class: target_pct}} with all 8 canonical
    classes per account (missing keys defaulted to 0.0).
    """
    cfg_path = _PROJECT_ROOT / "config" / "risk_parity_targets.yaml"
    if not cfg_path.exists():
        logger.warning(f"  targets YAML missing at {cfg_path} — using built-in defaults")
        targets = DEFAULT_TARGETS
    else:
        try:
            raw = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception as e:
            logger.warning(f"  targets YAML parse failed ({e}) — using defaults")
            raw = DEFAULT_TARGETS
        targets = {acct: dict(v or {}) for acct, v in raw.items()}

    # Normalise — every account gets every canonical class (default 0.0).
    out: dict[str, dict[str, float]] = {}
    for acct in ("caspar", "sarah"):
        per = {cls: 0.0 for cls in CANONICAL_ASSET_CLASSES}
        per.update({
            cls: float(v or 0.0) for cls, v in (targets.get(acct) or {}).items()
            if cls in CANONICAL_ASSET_CLASSES
        })
        out[acct] = per

    # Sanity: warn if a per-account total deviates from 100 by more than 1%.
    for acct, per in out.items():
        total = sum(per.values())
        if abs(total - 100.0) > 1.0:
            logger.warning(f"  targets for {acct} sum to {total:.1f}% (expected 100%)")
    return out


# --- portfolio readers -----------------------------------------------------

def _read_latest_rows(client, tab_name: str, logger: logging.Logger) -> list[dict]:
    """Return the rows from the LATEST date in `tab_name` as list of dicts."""
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


def _to_float(v, default: float = 0.0) -> float:
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def read_account_state(
    client, account: str, logger: logging.Logger,
) -> tuple[float, dict[str, float]]:
    """
    Returns (net_liq, capital_by_class) for one account.

    capital_by_class is in the account's native currency (USD for Caspar,
    SGD for Sarah). The map keys are the 8 canonical asset classes; missing
    classes are absent (caller fills with 0.0).

    Stocks: read latest positions_<account> rows, sum mkt_val per class.
    Options: read latest options rows for the account, sum mkt_val per
             class (option mark-to-market value, which is positive for
             long options and negative for short — short CSP/CC have
             negative mkt_val that *reduces* the class's capital footprint,
             which is the right behavior since the cash is locked elsewhere).

    Cash is NOT bucketed — it sits outside the asset-class taxonomy. The
    sum of (capital_by_class) + (cash) ≈ NLV. Capital_pct is computed
    against NLV so cash counts as the residual against 100%.

    Special handling: Sarah's positions_sarah.mkt_val is stored in raw
    quote currency (USD for US tickers, SGD for SGX). We convert USD →
    SGD using the macro tab's latest usd_sgd rate so all values are in
    Sarah's account currency (SGD) before bucketing.
    """
    snap_tab = f"snapshot_{account}"
    pos_tab = f"positions_{account}"

    snap_rows = _read_latest_rows(client, snap_tab, logger)
    pos_rows = _read_latest_rows(client, pos_tab, logger)

    nlv_field = "net_liq_usd" if account == "caspar" else "net_liq_sgd"
    if snap_rows:
        # Use the LATEST timestamp within the latest date.
        snap_rows.sort(key=lambda r: r.get("date", ""))
        net_liq = _to_float(snap_rows[-1].get(nlv_field))
    else:
        net_liq = 0.0

    if net_liq <= 0:
        logger.warning(f"  [{account}] net_liq is 0 or unreadable — skipping")
        return 0.0, {}

    # FX rate for Sarah (need to convert USD-quoted mkt_val → SGD).
    usd_sgd = 1.0
    if account == "sarah":
        macro_rows = _read_latest_rows(client, "macro", logger)
        if macro_rows:
            macro_rows.sort(key=lambda r: r.get("date", ""))
            usd_sgd = _to_float(macro_rows[-1].get("usd_sgd"), 1.0) or 1.0

    # SGX tickers — already quoted in SGD by the grab; don't double-convert.
    SGX = {"C6L", "G3B", "ES3"}

    capital: dict[str, float] = defaultdict(float)

    # --- stocks: dedupe to LATEST timestamp per ticker, then sum -----------
    # positions_<account> can have multiple rows per ticker per day (hourly
    # yahoo grabs). Use the row with the largest timestamp suffix per ticker.
    latest_by_ticker: dict[str, dict] = {}
    for r in pos_rows:
        t = (r.get("ticker") or "").strip().upper()
        if not t:
            continue
        prev = latest_by_ticker.get(t)
        if prev is None or r.get("date", "") > prev.get("date", ""):
            latest_by_ticker[t] = r

    for t, r in latest_by_ticker.items():
        cls = get_asset_class(t)
        mkt_val = _to_float(r.get("mkt_val"))
        # Sarah: convert USD-quoted positions to SGD (SGX already in SGD).
        if account == "sarah" and t not in SGX:
            mkt_val = mkt_val * usd_sgd
        capital[cls] += mkt_val

    # --- options: latest row per (account, ticker, right, strike, expiry) -
    # Options are MTM value; for short options this is typically negative.
    # We add it raw — the cash_required for a CSP is already implicit in the
    # cash bucket of NLV, so the option's MTM is the only incremental capital
    # delta to attribute to the underlying's class.
    opt_rows = _read_latest_rows(client, "options", logger)
    latest_opt: dict[tuple, dict] = {}
    for r in opt_rows:
        if (r.get("account") or "").strip() != account:
            continue
        t = (r.get("ticker") or "").strip().upper()
        if not t:
            continue
        key = (t, r.get("right"), r.get("strike"), r.get("expiry"))
        prev = latest_opt.get(key)
        if prev is None or r.get("date", "") > prev.get("date", ""):
            latest_opt[key] = r

    for r in latest_opt.values():
        t = (r.get("ticker") or "").strip().upper()
        cls = get_asset_class(t)
        mkt_val = _to_float(r.get("mkt_val"))
        # Options are USD-denominated for both accounts (US options market).
        # Sarah: convert to SGD for consistency with stock side.
        if account == "sarah":
            mkt_val = mkt_val * usd_sgd
        capital[cls] += mkt_val

    return net_liq, dict(capital)


# --- audit math ------------------------------------------------------------

def classify_action(delta_pct: float, threshold: float = 5.0) -> str:
    """Classify a delta_pct value as OVERWEIGHT / UNDERWEIGHT / ON_TARGET."""
    if delta_pct > threshold:
        return "OVERWEIGHT"
    if delta_pct < -threshold:
        return "UNDERWEIGHT"
    return "ON_TARGET"


def build_audit_rows(
    account: str,
    net_liq: float,
    capital_by_class: dict[str, float],
    targets: dict[str, float],
    date: str,
) -> list[S.RiskParityAuditRow]:
    """
    Build the 8 RiskParityAuditRow rows for one account. Always emits one
    row per canonical asset class — including classes with 0% capital, so
    UNDERWEIGHT recommendations (e.g. user's current 0% bond allocation)
    are surfaced explicitly rather than silently absent.
    """
    if net_liq <= 0:
        return []

    # --- step 1: capital_pct per class -----------------------------------
    capital_pct: dict[str, float] = {
        cls: (capital_by_class.get(cls, 0.0) / net_liq) * 100.0
        for cls in CANONICAL_ASSET_CLASSES
    }

    # --- step 2: vol_pct per class (static lookup) -----------------------
    vol_pct: dict[str, float] = {
        cls: VOL_BY_CLASS.get(cls, 18.0) for cls in CANONICAL_ASSET_CLASSES
    }

    # --- step 3: risk_contribution_pct (normalized) -----------------------
    # Risk contribution = capital_pct × vol_pct. Normalize so the total
    # across all 8 classes sums to 100%. This makes risk weight directly
    # comparable to capital weight, regardless of absolute vol levels.
    raw_rc = {
        cls: capital_pct[cls] * vol_pct[cls]
        for cls in CANONICAL_ASSET_CLASSES
    }
    total_rc = sum(raw_rc.values())
    if total_rc > 0:
        risk_contribution_pct = {
            cls: (raw_rc[cls] / total_rc) * 100.0
            for cls in CANONICAL_ASSET_CLASSES
        }
    else:
        risk_contribution_pct = {cls: 0.0 for cls in CANONICAL_ASSET_CLASSES}

    # --- step 4: deltas + actions + rebalance amount ---------------------
    rows: list[S.RiskParityAuditRow] = []
    for cls in CANONICAL_ASSET_CLASSES:
        cap = capital_pct[cls]
        target = targets.get(cls, 0.0)
        delta = cap - target
        action = classify_action(delta)
        rebalance_amt = abs(delta / 100.0) * net_liq

        # --- rationale ----
        ccy = "USD" if account == "caspar" else "SGD"
        if action == "ON_TARGET":
            rationale = (
                f"{cls} at {cap:.1f}% (target {target:.0f}%, delta {delta:+.1f}). "
                f"Within ±5% tolerance. Risk contrib {risk_contribution_pct[cls]:.1f}%."
            )
        elif action == "UNDERWEIGHT":
            verb = "Add" if cap < target else "Hold"
            rationale = (
                f"{cls} at {cap:.1f}% vs target {target:.0f}% (delta {delta:+.1f}). "
                f"{verb} ~{rebalance_amt:,.0f} {ccy} to reach target. "
                f"Risk contrib {risk_contribution_pct[cls]:.1f}%."
            )
        else:  # OVERWEIGHT
            rationale = (
                f"{cls} at {cap:.1f}% vs target {target:.0f}% (delta {delta:+.1f}). "
                f"Trim ~{rebalance_amt:,.0f} {ccy} to reach target. "
                f"Risk contrib {risk_contribution_pct[cls]:.1f}%."
            )

        rows.append(S.RiskParityAuditRow(
            date=date,
            account=account,
            asset_class=cls,
            capital_pct=cap,
            vol_pct=vol_pct[cls],
            risk_contribution_pct=risk_contribution_pct[cls],
            target_pct=target,
            delta_pct=delta,
            rebalance_action=action,
            rebalance_amount_usd=rebalance_amt,
            rationale=rationale,
        ))
    return rows


# --- main ------------------------------------------------------------------

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("risk_parity_audit")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _print_dry_table(rows: list[S.RiskParityAuditRow]) -> None:
    """Compact table print for --dry runs."""
    print(
        f"  {'account':8} {'asset_class':22} {'cap%':>6} {'vol%':>6} "
        f"{'risk%':>6} {'tgt%':>5} {'dlt%':>6} {'action':12} {'rebal_amt':>14}"
    )
    print(f"  {'-'*8} {'-'*22} {'-'*6} {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*12} {'-'*14}")
    for r in rows:
        ccy = "USD" if r.account == "caspar" else "SGD"
        print(
            f"  {r.account:8} {r.asset_class:22} "
            f"{r.capital_pct:>6.1f} {r.vol_pct:>6.1f} "
            f"{r.risk_contribution_pct:>6.1f} {r.target_pct:>5.0f} "
            f"{r.delta_pct:>+6.1f} {r.rebalance_action:12} "
            f"{r.rebalance_amount_usd:>10,.0f} {ccy}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="parse only, print 16 rows; no Sheet write")
    args = parser.parse_args()

    load_env()
    logger = setup_logger()

    today = S.now_sgt_date()
    logger.info(f"risk_parity_audit start (date={today}, dry={args.dry})")

    try:
        client = sh.authenticate()
    except Exception as e:
        logger.error(f"sheets auth failed: {e}")
        return 2

    targets = load_targets(logger)
    logger.info(f"  targets: caspar={sum(targets['caspar'].values()):.0f}%, "
                f"sarah={sum(targets['sarah'].values()):.0f}%")

    all_rows: list[S.RiskParityAuditRow] = []
    for account in ("caspar", "sarah"):
        net_liq, capital_by_class = read_account_state(client, account, logger)
        if net_liq <= 0:
            logger.warning(f"  [{account}] skipped — no NLV available")
            continue
        ccy = "USD" if account == "caspar" else "SGD"
        logger.info(f"  [{account}] NLV={net_liq:,.0f} {ccy} | classes seen: {len(capital_by_class)}")
        for cls, val in sorted(capital_by_class.items(), key=lambda kv: -kv[1]):
            pct = (val / net_liq) * 100.0
            logger.info(f"    {cls:24} {val:>12,.0f} {ccy} ({pct:>5.1f}%)")
        rows = build_audit_rows(
            account=account,
            net_liq=net_liq,
            capital_by_class=capital_by_class,
            targets=targets[account],
            date=today,
        )
        all_rows.extend(rows)

    if not all_rows:
        logger.error("no rows produced — both accounts had unreadable NLV")
        return 1

    n_over = sum(1 for r in all_rows if r.rebalance_action == "OVERWEIGHT")
    n_under = sum(1 for r in all_rows if r.rebalance_action == "UNDERWEIGHT")
    n_ok = sum(1 for r in all_rows if r.rebalance_action == "ON_TARGET")
    logger.info(
        f"built {len(all_rows)} rows: {n_over} OVERWEIGHT, {n_under} UNDERWEIGHT, "
        f"{n_ok} ON_TARGET"
    )

    if args.dry:
        _print_dry_table(all_rows)
        return 0

    try:
        sh.ensure_headers(client, S.RiskParityAuditRow.TAB_NAME, S.RiskParityAuditRow.HEADERS)
        n = sh.append_rows(client, S.RiskParityAuditRow.TAB_NAME, [r.to_row() for r in all_rows])
        logger.info(f"appended {n} rows to {S.RiskParityAuditRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"sheets write failed: {e}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
