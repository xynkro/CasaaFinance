"""
option_scanner.py — For each ticker in the watchlist, pull the option chain at
target DTE, find the optimal-delta put (CSP candidate) and call (CC candidate),
compute premium/yield/IV rank, and combine with the technical score into a
composite attractiveness ranking.

Output: per-ticker per-strategy ScanResultRow, sorted by composite score.

Composite = weighted blend of:
  - technical_score (strategy-specific)
  - annualized_yield_pct
  - iv_rank (implied vol percentile vs 52w)
  - cash_efficiency (premium / cash_required)
  - liquidity (tighter bid-ask = higher)

Literature-backed parameters:
  - CSP delta: 0.25-0.30 (~5-8% OTM) — ArXiv 2508.16598
  - CC delta:  0.10-0.16 — BXM index construction, Tastytrade research
  - DTE:       30-45d entry (45 ideal) — Tastytrade 200K+ trade backtest
  - Position sizing: Half-Kelly (f/2) — Frontiers 2020: 25% max DD vs 48% full Kelly
  - Max concurrent: 5 per account — CFA diversification + Kelly concentration risk
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

# Target parameters — literature-backed (ArXiv 2508.16598, Tastytrade, BXM)
# CSP: 25-30 delta (~5-8% OTM) — optimal risk-adjusted per put-writing study
# CC:  10-16 delta — BXM index construction, lower delta = less call-away risk
TARGET_DELTA_CSP = 0.27       # midpoint of 0.25-0.30 range
TARGET_DELTA_CC = 0.13        # midpoint of 0.10-0.16 range
DELTA_RANGE_CSP = (0.15, 0.35)  # acceptable scan range for CSP
DELTA_RANGE_CC = (0.08, 0.20)   # acceptable scan range for CC
TARGET_DTE_MIN = 30
TARGET_DTE_MAX = 45

# Position sizing — Half-Kelly (Frontiers in Applied Math 2020)
# Full Kelly: 48% max drawdown. Half-Kelly: 25% max drawdown.
MAX_POSITION_PCT = 0.05       # hard cap: 5% of account per position
MAX_CONCURRENT_SHORT = 5      # CFA diversification: max 5 short options per account
HALF_KELLY_FRACTION = 0.5     # fractional Kelly divisor

# IV Rank Gate — only sell premium when implied vol is rich relative to history.
# Volatility Risk Premium: IV exceeds realized vol by 4.2pp on average (CBOE since 1990).
# Selling at low IV rank captures almost no premium edge; selling at high IV rank
# captures the full VRP + elevated time decay.
IV_RANK_GATE_LOW = 30         # below this: SKIP premium selling (IV too cheap)
IV_RANK_GATE_HIGH = 70        # above this: BOOST composite score (IV rich)
IV_RANK_BOOST = 10            # composite score bonus when IV rank > high gate
IV_RANK_PENALTY = -15         # composite score penalty when IV rank < low gate (soft gate)

# VIX Regime Switching — mechanical strategy adjustment based on market-wide IV.
# VIX <15:  low vol regime — aggressive premium selling (higher delta, larger size OK)
# VIX 15-25: standard regime — normal parameters
# VIX 25-35: elevated regime — reduce position size, tighter delta, faster exits
# VIX >35:  crisis regime — buy protection only, no new short premium
VIX_REGIME_LOW = 15
VIX_REGIME_STANDARD = 25
VIX_REGIME_ELEVATED = 35

VIX_REGIME_RULES: dict[str, dict] = {
    "low_vol": {
        "delta_adj": 0.03,        # bump target delta +3 (more aggressive)
        "composite_adj": 5,       # slight composite boost
        "size_mult": 1.0,         # full size
        "allow_new_short": True,
        "description": "VIX<15: low vol — aggressive premium selling",
    },
    "standard": {
        "delta_adj": 0.0,
        "composite_adj": 0,
        "size_mult": 1.0,
        "allow_new_short": True,
        "description": "VIX 15-25: standard regime",
    },
    "elevated": {
        "delta_adj": -0.05,       # pull delta back (more OTM = safer)
        "composite_adj": -10,     # penalize new entries
        "size_mult": 0.5,         # half size
        "allow_new_short": True,  # still allowed, but reduced
        "description": "VIX 25-35: elevated — reduce exposure",
    },
    "crisis": {
        "delta_adj": 0.0,
        "composite_adj": -50,     # heavy penalty — basically suppresses new entries
        "size_mult": 0.0,         # no new positions
        "allow_new_short": False,
        "description": "VIX>35: crisis — buy protection only",
    },
}


def classify_vix_regime(vix: float) -> str:
    """Classify current VIX into regime bucket."""
    if vix <= 0:
        return "standard"  # missing data — assume normal
    if vix < VIX_REGIME_LOW:
        return "low_vol"
    if vix < VIX_REGIME_STANDARD:
        return "standard"
    if vix < VIX_REGIME_ELEVATED:
        return "elevated"
    return "crisis"


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
    target_delta: float = 0.25,
    delta_range: tuple[float, float] = (0.10, 0.40),
) -> Optional[dict[str, Any]]:
    """
    Find the strike closest to target_delta on the given side.
    Filters to delta_range (strategy-specific).
    Return dict with strike, premium, delta, yield, bid/ask, iv.
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
    delta_lo, delta_hi = delta_range

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
            # Strategy-specific delta range filter
            if delta_mag < delta_lo or delta_mag > delta_hi:
                continue

            diff = abs(delta_mag - target_delta)
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


def _half_kelly_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    account_value: float,
) -> float:
    """
    Compute half-Kelly position size in dollars.

    Kelly fraction: f = (win_rate × avg_win - loss_rate × avg_loss) / avg_win
    Half-Kelly: f/2 — reduces max drawdown from ~48% to ~25% (Frontiers 2020).
    Hard cap: MAX_POSITION_PCT of account value.

    Returns max cash to allocate to one position.
    """
    if avg_win <= 0 or account_value <= 0:
        return account_value * MAX_POSITION_PCT
    loss_rate = 1 - win_rate
    kelly_f = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
    kelly_f = max(0, kelly_f)  # never go negative (don't bet if edge is negative)
    half_kelly = kelly_f * HALF_KELLY_FRACTION
    # Cap at MAX_POSITION_PCT
    position_pct = min(half_kelly, MAX_POSITION_PCT)
    return account_value * position_pct


def scan_watchlist(
    tickers: list[str],
    indicators: dict[str, dict],
    technical_scores: dict[str, dict[str, float]],
    sgx_tickers: set[str],
    available_cash_by_account: dict[str, float],
    today: str,
    current_short_count_by_account: dict[str, int] | None = None,
    vix: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Scan every ticker for CSP + CC candidates.
    Returns list of dicts (one per {ticker, strategy} combo that produced a candidate).

    Uses strategy-specific delta targets:
      CSP: 0.25-0.30 delta (ArXiv 2508.16598 — 5-10% OTM optimal)
      CC:  0.10-0.16 delta (BXM construction — lower call-away risk)

    Includes:
      - Half-Kelly sizing recommendation and max concurrent guard
      - IV Rank Gate: skip/penalize low-IV-rank entries, boost high-IV-rank
      - VIX Regime Switching: mechanical adjustments per VIX level
      - Post-Earnings IV Crush: boost recently-reported tickers with IV collapse
    """
    results = []

    # VIX regime classification
    vix_regime = classify_vix_regime(vix)
    vix_rules = VIX_REGIME_RULES[vix_regime]

    # Estimate total account value for Kelly sizing (sum of all accounts)
    total_account_value = sum(available_cash_by_account.values()) if available_cash_by_account else 0
    # Default win rate / avg win/loss for short premium (Tastytrade empirical)
    default_win_rate = 0.70   # 70% win rate at 25-30 delta, 45 DTE
    default_avg_win = 0.50    # avg win = 50% of credit (profit target)
    default_avg_loss = 1.50   # avg loss = 1.5× credit

    kelly_max = _half_kelly_size(
        default_win_rate, default_avg_win, default_avg_loss, total_account_value,
    ) if total_account_value > 0 else 0

    # Max concurrent guard
    short_counts = current_short_count_by_account or {}
    at_capacity = any(
        count >= MAX_CONCURRENT_SHORT
        for count in short_counts.values()
    ) if short_counts else False

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

        # Post-Earnings IV Crush detection:
        # If ticker just reported earnings (1-3 days ago), IV collapses 30-60%.
        # This is the ideal window to sell premium — elevated base IV + crush = fast decay.
        earnings_days = int(ind.get("earnings_days_away", -1))
        is_post_earnings = -3 <= earnings_days <= 0  # reported 0-3 days ago
        post_earnings_boost = 8 if is_post_earnings else 0  # composite bonus

        # VIX regime delta adjustment — shift target delta per regime
        csp_delta_adj = TARGET_DELTA_CSP + vix_rules["delta_adj"]
        cc_delta_adj = TARGET_DELTA_CC + vix_rules["delta_adj"]
        # Clamp to sane ranges
        csp_delta_adj = max(0.10, min(0.40, csp_delta_adj))
        cc_delta_adj = max(0.05, min(0.25, cc_delta_adj))

        # ---- CSP candidate (short put, 0.25-0.30Δ) ----
        csp = _scan_one_side(
            ysym, expiry, "P", underlying, sigma_annual, dte,
            target_delta=csp_delta_adj,
            delta_range=DELTA_RANGE_CSP,
        )
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

            # --- IV Rank Gate ---
            iv_gate_note = ""
            if iv_rank_est < IV_RANK_GATE_LOW:
                composite += IV_RANK_PENALTY  # soft gate: heavily penalize, don't hard-block
                iv_gate_note = f"IV_RANK_LOW ({iv_rank_est:.0f}<{IV_RANK_GATE_LOW})"
            elif iv_rank_est > IV_RANK_GATE_HIGH:
                composite += IV_RANK_BOOST
                iv_gate_note = f"IV_RANK_RICH ({iv_rank_est:.0f}>{IV_RANK_GATE_HIGH})"

            # --- VIX Regime adjustment ---
            composite += vix_rules["composite_adj"]
            vix_note = ""
            if vix_regime != "standard":
                vix_note = f"VIX_{vix_regime.upper()} ({vix:.1f})"

            # --- Post-Earnings IV Crush boost ---
            composite += post_earnings_boost
            earnings_note = ""
            if is_post_earnings:
                earnings_note = f"POST_EARNINGS_CRUSH (reported {abs(earnings_days)}d ago)"

            # --- VIX crisis gate: block new short premium ---
            if not vix_rules["allow_new_short"]:
                composite = max(0, composite - 50)  # crush score to near-zero

            composite = max(0.0, min(100.0, composite))

            # Half-Kelly sizing recommendation (scaled by VIX regime)
            effective_kelly = kelly_max * vix_rules["size_mult"]
            sizing_note = ""
            if effective_kelly > 0 and csp["cash_required"] > effective_kelly:
                sizing_note = f"OVERSIZED: ${csp['cash_required']:.0f} > half-Kelly ${effective_kelly:.0f}"
            if vix_rules["size_mult"] < 1.0 and vix_rules["size_mult"] > 0:
                sizing_note = (sizing_note + " | " if sizing_note else "") + f"VIX_REDUCED: {vix_rules['size_mult']:.0%} size"

            result = {
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
                "kelly_max_cash": effective_kelly,
                "sizing_note": sizing_note,
                "at_capacity": at_capacity,
                "vix_regime": vix_regime,
                "iv_gate_note": iv_gate_note,
                "vix_note": vix_note,
                "earnings_note": earnings_note,
                "post_earnings": is_post_earnings,
            }
            if at_capacity:
                result["sizing_note"] = f"AT CAPACITY: {MAX_CONCURRENT_SHORT} short options already open"
            if not vix_rules["allow_new_short"]:
                result["sizing_note"] = f"VIX CRISIS ({vix:.1f}): no new short premium"
            results.append(result)

        # ---- CC candidate (short call, 0.10-0.16Δ) ----
        cc = _scan_one_side(
            ysym, expiry, "C", underlying, sigma_annual, dte,
            target_delta=cc_delta_adj,
            delta_range=DELTA_RANGE_CC,
        )
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

            # --- IV Rank Gate ---
            iv_gate_note = ""
            if iv_rank_est < IV_RANK_GATE_LOW:
                composite += IV_RANK_PENALTY
                iv_gate_note = f"IV_RANK_LOW ({iv_rank_est:.0f}<{IV_RANK_GATE_LOW})"
            elif iv_rank_est > IV_RANK_GATE_HIGH:
                composite += IV_RANK_BOOST
                iv_gate_note = f"IV_RANK_RICH ({iv_rank_est:.0f}>{IV_RANK_GATE_HIGH})"

            # --- VIX Regime adjustment ---
            composite += vix_rules["composite_adj"]
            vix_note = ""
            if vix_regime != "standard":
                vix_note = f"VIX_{vix_regime.upper()} ({vix:.1f})"

            # --- Post-Earnings IV Crush boost ---
            composite += post_earnings_boost
            earnings_note = ""
            if is_post_earnings:
                earnings_note = f"POST_EARNINGS_CRUSH (reported {abs(earnings_days)}d ago)"

            # --- VIX crisis gate ---
            if not vix_rules["allow_new_short"]:
                composite = max(0, composite - 50)

            composite = max(0.0, min(100.0, composite))

            effective_kelly = kelly_max * vix_rules["size_mult"]
            sizing_note = ""
            if effective_kelly > 0 and cc["cash_required"] > effective_kelly:
                sizing_note = f"OVERSIZED: ${cc['cash_required']:.0f} > half-Kelly ${effective_kelly:.0f}"
            if vix_rules["size_mult"] < 1.0 and vix_rules["size_mult"] > 0:
                sizing_note = (sizing_note + " | " if sizing_note else "") + f"VIX_REDUCED: {vix_rules['size_mult']:.0%} size"

            result = {
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
                "kelly_max_cash": effective_kelly,
                "sizing_note": sizing_note,
                "at_capacity": at_capacity,
                "vix_regime": vix_regime,
                "iv_gate_note": iv_gate_note,
                "vix_note": vix_note,
                "earnings_note": earnings_note,
                "post_earnings": is_post_earnings,
            }
            if at_capacity:
                result["sizing_note"] = f"AT CAPACITY: {MAX_CONCURRENT_SHORT} short options already open"
            if not vix_rules["allow_new_short"]:
                result["sizing_note"] = f"VIX CRISIS ({vix:.1f}): no new short premium"
            results.append(result)

    # Sort by composite score descending
    results.sort(key=lambda r: r["composite_score"], reverse=True)
    return results
