"""
option_scanner.py — For each ticker in the watchlist, pull the option chain at
target DTE, find the ~0.25Δ put (CSP candidate) and ~0.25Δ call (CC candidate),
compute premium/yield/IV rank, and combine with the technical score into a
composite attractiveness ranking.

Output: per-ticker per-strategy ScanResultRow, sorted by composite score.

Composite = weighted blend of:
  - technical_score (strategy-specific)
  - annualized_yield_pct
  - iv_rank (implied vol percentile vs 52w)
  - cash_efficiency (premium / cash_required)
  - liquidity (tighter bid-ask = higher)
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Optional

from src.wheel_continuation import bs_delta


# ---- Composite weights (must sum to 1.0) ----
W_TECHNICAL = 0.40
W_YIELD = 0.25
W_IV_RANK = 0.20
W_CASH_EFF = 0.10
W_LIQUIDITY = 0.05

# Target parameters
TARGET_DELTA = 0.25
TARGET_DTE_MIN = 30
TARGET_DTE_MAX = 45


def yahoo_symbol(sym: str, sgx_tickers: set[str]) -> str:
    return f"{sym}.SI" if sym.upper() in sgx_tickers else sym.upper()


def _find_target_expiry(yahoo_sym: str) -> Optional[str]:
    """Pick the expiry closest to middle of target DTE window."""
    import yfinance as yf

    try:
        t = yf.Ticker(yahoo_sym)
        exps = list(t.options)
    except Exception:
        return None

    today = date.today()
    target_mid = (TARGET_DTE_MIN + TARGET_DTE_MAX) // 2
    best_exp, best_diff = None, float("inf")
    for exp in exps:
        try:
            ed = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = (ed - today).days
            if TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
                diff = abs(dte - target_mid)
                if diff < best_diff:
                    best_diff = diff
                    best_exp = exp
        except ValueError:
            continue
    return best_exp


def _iv_rank(iv_now: float, iv_history: list[float]) -> float:
    """IV percentile over history (0-100)."""
    if not iv_history or iv_now <= 0:
        return 0.0
    low, high = min(iv_history), max(iv_history)
    if high <= low:
        return 50.0
    return round((iv_now - low) / (high - low) * 100, 1)


def _scan_one_side(
    yahoo_sym: str,
    expiry: str,
    right: str,
    underlying_last: float,
    sigma_annual: float,
    dte: int,
) -> Optional[dict[str, Any]]:
    """
    Find the ~0.25Δ strike on the given side. Return dict with strike, premium,
    delta, yield, bid/ask, iv.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(yahoo_sym)
        chain = t.option_chain(expiry)
    except Exception:
        return None

    df = chain.puts if right == "P" else chain.calls
    if df is None or df.empty:
        return None

    T = max(dte, 1) / 365.0
    best = None
    best_delta_diff = float("inf")

    for _, row in df.iterrows():
        try:
            K = float(row["strike"])
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            last_p = float(row.get("lastPrice", 0) or 0)
            volume = int(row.get("volume", 0) or 0)
            oi = int(row.get("openInterest", 0) or 0)

            # Liquidity filter: need some evidence of real trading
            has_quote = bid > 0.01 and ask > 0.01
            has_activity = volume >= 10 or oi >= 50
            if not (has_quote or has_activity):
                continue

            # Prefer live quote midpoint; fall back to lastPrice if quote stale
            if has_quote:
                mid = (bid + ask) / 2
            elif has_activity and last_p > 0.05:
                mid = last_p
            else:
                continue

            if mid <= 0.05:  # penny options are noise
                continue

            iv = float(row.get("impliedVolatility", 0) or 0)
            # Filter placeholder IVs (Yahoo returns 0.5 for many stale quotes)
            # Also cap extreme IVs that would pass through noise
            if iv <= 0.05 or iv >= 3.0 or abs(iv - 0.5) < 0.001:
                vol_for_delta = sigma_annual if sigma_annual > 0 else 0.4
                iv_valid = False
            else:
                vol_for_delta = iv
                iv_valid = True

            delta = bs_delta(underlying_last, K, T, vol_for_delta, 0.045, right)
            delta_mag = abs(delta)
            # Skip extreme-delta strikes — we want 0.10 to 0.40 range
            if delta_mag < 0.05 or delta_mag > 0.45:
                continue

            diff = abs(delta_mag - TARGET_DELTA)
            if diff < best_delta_diff:
                best_delta_diff = diff
                cash_required = K * 100 if right == "P" else underlying_last * 100
                annual_yield = (mid / K) * (365 / max(dte, 1)) * 100 if K > 0 else 0
                breakeven = (K - mid) if right == "P" else (K + mid)
                spread_pct = ((ask - bid) / mid * 100) if (bid > 0 and ask > 0 and mid > 0) else 100
                best = {
                    "strike": K, "premium": mid, "bid": bid, "ask": ask,
                    "delta": delta, "delta_mag": delta_mag,
                    "iv": iv if iv_valid else 0, "cash_required": cash_required,
                    "annual_yield_pct": annual_yield, "breakeven": breakeven,
                    "spread_pct": spread_pct,
                    "volume": volume, "open_interest": oi,
                }
        except (ValueError, KeyError):
            continue
    return best


def _normalize(value: float, lo: float, hi: float) -> float:
    """Clamp + normalize value into [0, 100]."""
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100))


def compute_composite(
    tech_score: float,
    yield_pct: float,
    iv_rank: float,
    cash_required: float,
    premium: float,
    spread_pct: float,
) -> float:
    """Composite attractiveness score [0, 100]."""
    # Normalize each component
    tech_norm = _normalize(tech_score, -100, 100)              # -100 → 0, +100 → 100
    yield_norm = _normalize(yield_pct, 0, 80)                  # 0% → 0, 80%+ → 100
    iv_norm = iv_rank                                          # already 0-100
    # Cash efficiency: premium per $1,000 of cash
    cash_eff = (premium * 100) / max(cash_required, 1) * 1000
    cash_norm = _normalize(cash_eff, 0, 15)                    # $15 premium per $1k ≈ 1.5%
    liq_norm = _normalize(100 - spread_pct, 0, 100)            # tighter spread = higher

    composite = (
        tech_norm * W_TECHNICAL
        + yield_norm * W_YIELD
        + iv_norm * W_IV_RANK
        + cash_norm * W_CASH_EFF
        + liq_norm * W_LIQUIDITY
    )
    return round(composite, 1)


def scan_watchlist(
    tickers: list[str],
    indicators: dict[str, dict],
    technical_scores: dict[str, dict[str, float]],
    sgx_tickers: set[str],
    available_cash_by_account: dict[str, float],
    today: str,
) -> list[dict[str, Any]]:
    """
    Scan every ticker for CSP + CC candidates.
    Returns list of dicts (one per {ticker, strategy} combo that produced a candidate).
    """
    results = []

    for sym in tickers:
        ind = indicators.get(sym, {})
        if not ind:
            continue
        underlying = float(ind.get("close", 0))
        sigma_annual = float(ind.get("volatility_annual", 0.4))
        if underlying <= 0:
            continue

        ysym = yahoo_symbol(sym, sgx_tickers)
        expiry = _find_target_expiry(ysym)
        if not expiry:
            continue
        dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - date.today()).days

        scores = technical_scores.get(sym, {})

        # ---- CSP candidate (short put, ~0.25Δ) ----
        csp = _scan_one_side(ysym, expiry, "P", underlying, sigma_annual, dte)
        if csp:
            iv_rank_est = 0.0  # IV rank requires 52w IV history; approximate from iv_annual
            # Simple proxy: compare current chain IV to realized vol
            if csp["iv"] > 0 and sigma_annual > 0:
                iv_ratio = csp["iv"] / sigma_annual
                iv_rank_est = _normalize(iv_ratio, 0.8, 2.0)  # 1x realized → ~40; 2x → 100

            composite = compute_composite(
                tech_score=scores.get("CSP", 0),
                yield_pct=csp["annual_yield_pct"],
                iv_rank=iv_rank_est,
                cash_required=csp["cash_required"],
                premium=csp["premium"],
                spread_pct=csp["spread_pct"],
            )
            results.append({
                "date": today, "ticker": sym, "strategy": "CSP", "right": "P",
                "strike": csp["strike"], "expiry": expiry.replace("-", ""),
                "dte": dte, "delta": csp["delta"],
                "premium": csp["premium"], "bid": csp["bid"], "ask": csp["ask"],
                "annual_yield_pct": csp["annual_yield_pct"],
                "cash_required": csp["cash_required"],
                "breakeven": csp["breakeven"],
                "iv": csp["iv"], "iv_rank": iv_rank_est,
                "spread_pct": csp["spread_pct"],
                "underlying_last": underlying,
                "technical_score": scores.get("CSP", 0),
                "composite_score": composite,
                "catalyst_flag": bool(ind.get("catalyst_flag", False)),
            })

        # ---- CC candidate (short call, ~0.25Δ) ----
        cc = _scan_one_side(ysym, expiry, "C", underlying, sigma_annual, dte)
        if cc:
            iv_rank_est = 0.0
            if cc["iv"] > 0 and sigma_annual > 0:
                iv_ratio = cc["iv"] / sigma_annual
                iv_rank_est = _normalize(iv_ratio, 0.8, 2.0)

            composite = compute_composite(
                tech_score=scores.get("CC", 0),
                yield_pct=cc["annual_yield_pct"],
                iv_rank=iv_rank_est,
                cash_required=cc["cash_required"],
                premium=cc["premium"],
                spread_pct=cc["spread_pct"],
            )
            results.append({
                "date": today, "ticker": sym, "strategy": "CC", "right": "C",
                "strike": cc["strike"], "expiry": expiry.replace("-", ""),
                "dte": dte, "delta": cc["delta"],
                "premium": cc["premium"], "bid": cc["bid"], "ask": cc["ask"],
                "annual_yield_pct": cc["annual_yield_pct"],
                "cash_required": cc["cash_required"],
                "breakeven": cc["breakeven"],
                "iv": cc["iv"], "iv_rank": iv_rank_est,
                "spread_pct": cc["spread_pct"],
                "underlying_last": underlying,
                "technical_score": scores.get("CC", 0),
                "composite_score": composite,
                "catalyst_flag": bool(ind.get("catalyst_flag", False)),
            })

    # Sort by composite score descending
    results.sort(key=lambda r: r["composite_score"], reverse=True)
    return results
