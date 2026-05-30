"""
portfolio_greeks.py — Book-level Greek aggregation for the open-option book.

The single most important risk number for a premium-selling book is net vega:
when the market sells off, IV spikes across *every* short position at once, so
per-trade delta limits miss the correlated tail. This module sums vega / theta /
gamma across open option positions and estimates the book P&L under a uniform
IV shock (the "what if VIX +Npts" line).

Per-position IV is solved from the option's last price when available (the
position's actual vol surface), falling back to the underlying's realized vol.

Pure / dependency-free (math + the Black-Scholes Greeks already in
wheel_continuation.py) so it is unit-testable without sheets or network.

Public API:
  position_greeks(opt, r=0.045)        -> dict per-position $ Greeks (qty-signed)
  aggregate_book_greeks(options, ...)  -> dict book totals + per-ticker breakdown
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from src.wheel_continuation import _norm_cdf, bs_gamma, bs_theta, bs_vega

CONTRACT_MULTIPLIER = 100
DEFAULT_RF = 0.045
_IV_LO, _IV_HI = 0.01, 5.0   # IV solver bracket (1% .. 500%)


def _bsm_price(S: float, K: float, T: float, sigma: float, r: float, right: str) -> float:
    """Black-Scholes option price (no dividends)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # Intrinsic at/after expiry
        return max(0.0, (S - K) if right == "C" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if right == "C":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def solve_iv(price: float, S: float, K: float, T: float, right: str,
             r: float = DEFAULT_RF) -> float:
    """
    Solve implied vol from an option price via bisection.
    Returns 0.0 if unsolvable (price below intrinsic, bad inputs, no convergence).
    """
    if price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
    intrinsic = max(0.0, (S - K) if right == "C" else (K - S))
    if price < intrinsic - 1e-6:
        return 0.0  # price below intrinsic — not solvable
    lo, hi = _IV_LO, _IV_HI
    p_lo = _bsm_price(S, K, T, lo, r, right) - price
    p_hi = _bsm_price(S, K, T, hi, r, right) - price
    if p_lo * p_hi > 0:
        return 0.0  # price outside [lo, hi] bracket
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        p_mid = _bsm_price(S, K, T, mid, r, right) - price
        if abs(p_mid) < 1e-6:
            return round(mid, 4)
        if p_lo * p_mid < 0:
            hi = mid
        else:
            lo, p_lo = mid, p_mid
    return round(0.5 * (lo + hi), 4)


def _dte_from(opt: dict[str, Any], today: date | None = None) -> int:
    """Days-to-expiry from the option dict — prefer explicit dte, else parse expiry."""
    dte = opt.get("dte")
    try:
        if dte not in (None, ""):
            return int(float(dte))
    except (TypeError, ValueError):
        pass
    exp = str(opt.get("expiry", "")).strip()
    if not exp:
        return 0
    ref = today or date.today()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return (datetime.strptime(exp, fmt).date() - ref).days
        except ValueError:
            continue
    return 0


def position_greeks(opt: dict[str, Any], r: float = DEFAULT_RF,
                    today: date | None = None) -> dict[str, Any]:
    """
    Per-position dollar Greeks, signed by qty (short qty < 0 flips the sign).

    opt keys used: right (C/P), strike, qty, underlying_last, last (option px),
                   volatility_annual (RV fallback), expiry/dte.

    Returns:
      {ticker, qty, vega, theta, gamma, iv, iv_source, valid}
      vega  = $ book change per +1 IV point        (short option → negative)
      theta = $ book change per calendar day        (short option → positive)
      gamma = position gamma (shares of delta per $1)  (short option → negative)
    """
    out = {
        "ticker": opt.get("ticker", ""),
        "qty": 0.0, "vega": 0.0, "theta": 0.0, "gamma": 0.0,
        "iv": 0.0, "iv_source": "none", "valid": False,
    }
    right = str(opt.get("right", "")).upper()
    if right not in ("C", "P"):
        return out  # not an option (stock row) — no Greeks
    try:
        S = float(opt.get("underlying_last", 0) or 0)
        K = float(opt.get("strike", 0) or 0)
        qty = float(opt.get("qty", 0) or 0)
        last = float(opt.get("last", 0) or 0)
        rv = float(opt.get("volatility_annual", 0) or 0)
    except (TypeError, ValueError):
        return out
    if S <= 0 or K <= 0 or qty == 0:
        return out
    dte = _dte_from(opt, today)
    if dte <= 0:
        return out
    T = dte / 365.0

    # Per-position IV: solve from the option's last price; fall back to RV.
    iv = solve_iv(last, S, K, T, right, r) if last > 0 else 0.0
    iv_source = "solved"
    if iv <= 0:
        iv = rv
        iv_source = "rv_fallback"
    if iv <= 0:
        return out

    contracts = qty * CONTRACT_MULTIPLIER  # signed
    out.update({
        "qty": qty,
        "vega": round(bs_vega(S, K, T, iv, r) * contracts, 2),
        "theta": round(bs_theta(S, K, T, iv, r, right) * contracts, 2),
        "gamma": round(bs_gamma(S, K, T, iv, r) * contracts, 4),
        "iv": round(iv, 4),
        "iv_source": iv_source,
        "valid": True,
    })
    return out


def aggregate_book_greeks(options: list[dict[str, Any]],
                          vix_shock_pts: float = 5.0,
                          r: float = DEFAULT_RF,
                          today: date | None = None) -> dict[str, Any]:
    """
    Sum signed Greeks across the open-option book and estimate the P&L under a
    uniform IV shock of `vix_shock_pts` points (the headline tail-risk number).

    vix_shock_pnl = net_vega * vix_shock_pts. NOTE: this models a uniform IV
    move across all names — a deliberately simple, conservative scenario, not a
    beta-weighted forecast. For a net-short-vega book it is negative (a vol
    spike hurts), which is exactly the number to watch.

    Returns:
      {net_vega, net_theta, net_gamma, vix_shock_pts, vix_shock_pnl,
       n_positions, n_valued, by_ticker}
    """
    net_vega = net_theta = net_gamma = 0.0
    n_valued = 0
    by_ticker: dict[str, dict[str, float]] = {}
    for opt in options:
        g = position_greeks(opt, r=r, today=today)
        if not g["valid"]:
            continue
        n_valued += 1
        net_vega += g["vega"]
        net_theta += g["theta"]
        net_gamma += g["gamma"]
        t = by_ticker.setdefault(g["ticker"], {"vega": 0.0, "theta": 0.0, "gamma": 0.0})
        t["vega"] += g["vega"]
        t["theta"] += g["theta"]
        t["gamma"] += g["gamma"]

    return {
        "net_vega": round(net_vega, 2),
        "net_theta": round(net_theta, 2),
        "net_gamma": round(net_gamma, 4),
        "vix_shock_pts": vix_shock_pts,
        "vix_shock_pnl": round(net_vega * vix_shock_pts, 2),
        "n_positions": len(options),
        "n_valued": n_valued,
        "by_ticker": {k: {kk: round(vv, 2) for kk, vv in v.items()}
                      for k, v in by_ticker.items()},
    }
