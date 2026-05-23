"""
term_structure.py — IV term structure analysis.

Computes term structure slope and ranks expiries by VRP-per-day.
Contango (long-term IV > short-term) predicts better short-vol
returns (OQuants S4, Sinclair "Positional Option Trading").
"""
from __future__ import annotations

import math


def compute_ts_slope(iv_short: float, iv_long: float,
                     dte_short: int, dte_long: int) -> float:
    """
    Term structure slope as annualised IV difference per sqrt-day.
    Positive = contango (normal, favorable for short vol).
    Negative = backwardation (stressed, unfavorable).

    Args:
        iv_short: IV of shorter-dated expiry (annualised, e.g. 0.25 = 25%)
        iv_long: IV of longer-dated expiry
        dte_short: Days to expiry for short-dated
        dte_long: Days to expiry for long-dated
    """
    if iv_short <= 0 or iv_long <= 0 or dte_short <= 0 or dte_long <= dte_short:
        return 0.0
    # Normalise to annualised basis via sqrt-time
    iv_diff = iv_long - iv_short
    time_diff = math.sqrt(dte_long / 365) - math.sqrt(dte_short / 365)
    if time_diff <= 0:
        return 0.0
    return round(iv_diff / time_diff, 4)


def rank_expiries(expiries: list[dict], rv_forecast: float) -> list[dict]:
    """
    Rank expiries by VRP edge per calendar day.

    VRP_per_day = (atm_iv - rv_forecast) / sqrt(dte)
    Shorter DTE with rich IV = more edge per day.

    Args:
        expiries: list of dicts with keys: expiry, dte, atm_iv, credit (optional)
        rv_forecast: realized vol forecast (annualised, e.g. 0.25)

    Returns:
        Same list sorted by vrp_per_day descending, with vrp_per_day added.
    """
    scored = []
    for e in expiries:
        iv = e.get("atm_iv", 0)
        dte = e.get("dte", 1)
        if iv <= 0 or dte <= 0:
            continue
        vrp_per_day = (iv - rv_forecast) / math.sqrt(dte) if rv_forecast > 0 else 0
        scored.append({**e, "vrp_per_day": round(vrp_per_day, 6)})
    scored.sort(key=lambda x: x["vrp_per_day"], reverse=True)
    return scored
