"""
wheel_continuation.py — For each open option, compute the "next leg" suggestion.

Answers: When AAPL 225P expires, what's next? Same underlying at ~25Δ?
Or should we switch to a better opportunity?

Logic per open option:
  - HOLD: OTM, healthy, >14 DTE → let it ride, stage next leg for preview
  - EXPIRING_WORTHLESS: OTM, ≤7 DTE, low assignment risk → suggest next
    ~25Δ strike at next monthly expiry
  - LIKELY_ASSIGNED: ITM or high confidence → plan post-assignment (switch
    from CSP→CC or CC→CSP)
  - CATALYST_WARNING: catalyst_flag on underlying → recommend lower delta
    (0.15-0.20) or switching underlying

Option chain fetching uses yfinance Ticker.option_chain(expiry).
Delta estimated via Black-Scholes since Yahoo doesn't always expose greeks.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Optional

# Config
TARGET_DELTA_CSP = 0.25
TARGET_DELTA_CC = 0.25
TARGET_DTE_MIN = 30
TARGET_DTE_MAX = 45
# When catalyst_flag is True, reduce target delta (less risk)
CATALYST_DELTA_ADJ = 0.10  # target becomes 0.15 instead of 0.25
# Score thresholds
MIN_SCORE_TO_STAY = 30   # CSP/CC score must be above this to stay on same ticker
SWITCH_SCORE_DELTA = 15  # score gap to recommend switching


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_delta(S: float, K: float, T: float, sigma: float, r: float, right: str) -> float:
    """Black-Scholes delta."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError):
        return 0.0
    if right == "C":
        return _norm_cdf(d1)
    else:
        return _norm_cdf(d1) - 1.0


def _fmt_yahoo_ticker(sym: str, sgx_tickers: set[str]) -> str:
    if sym.upper() in sgx_tickers:
        return f"{sym.upper()}.SI"
    return sym.upper()


def _find_monthly_expiries(yahoo_sym: str, target_dte_min: int, target_dte_max: int) -> list[str]:
    """Return option expiries falling inside the target DTE window."""
    import yfinance as yf
    try:
        t = yf.Ticker(yahoo_sym)
        exps = list(t.options)  # list of "YYYY-MM-DD"
    except Exception:
        return []
    today = date.today()
    candidates = []
    for exp in exps:
        try:
            ed = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = (ed - today).days
            if target_dte_min <= dte <= target_dte_max:
                candidates.append(exp)
        except ValueError:
            continue
    return candidates


def _find_best_strike(
    yahoo_sym: str,
    expiry: str,
    right: str,
    target_delta: float,
    underlying: float,
    sigma_annual: float,
    dte: int,
    r: float = 0.045,
) -> Optional[dict[str, Any]]:
    """
    Fetch option chain at `expiry` and find the strike with delta closest to target.
    Returns dict with strike, premium, delta, breakeven, bid, ask.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(yahoo_sym)
        chain = t.option_chain(expiry)
    except Exception:
        return None

    df = chain.calls if right == "C" else chain.puts
    if df is None or df.empty:
        return None

    T = max(dte, 1) / 365.0
    sigma = sigma_annual if sigma_annual > 0 else 0.4

    best = None
    best_delta_diff = float("inf")

    for _, row in df.iterrows():
        try:
            K = float(row["strike"])
            bid = float(row.get("bid", 0))
            ask = float(row.get("ask", 0))
            mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else float(row.get("lastPrice", 0))
            if mid <= 0:
                continue

            # Yahoo sometimes provides impliedVolatility; prefer it over our HV
            iv = float(row.get("impliedVolatility", 0) or 0)
            vol_for_delta = iv if iv > 0 else sigma

            delta = bs_delta(underlying, K, T, vol_for_delta, r, right)
            # For puts delta is negative; we compare |delta| to target
            delta_mag = abs(delta)
            diff = abs(delta_mag - target_delta)
            if diff < best_delta_diff:
                best_delta_diff = diff
                # Yield (annualized): premium / cash_required * (365 / dte)
                cash_required = K * 100 if right == "P" else underlying * 100
                annual_yield = (mid / K) * (365 / max(dte, 1)) * 100 if K > 0 else 0
                breakeven = (K - mid) if right == "P" else (K + mid)
                best = {
                    "strike": K,
                    "premium": mid,
                    "bid": bid,
                    "ask": ask,
                    "delta": delta,
                    "delta_mag": delta_mag,
                    "expiry": expiry,
                    "iv": iv,
                    "annual_yield_pct": annual_yield,
                    "breakeven": breakeven,
                    "cash_required": cash_required,
                }
        except (ValueError, KeyError):
            continue

    return best


def _status_from_option(dte: int, confidence_pct: int, moneyness: str, catalyst_flag: bool) -> str:
    """Classify current option status to route the decision."""
    if dte <= 0:
        return "EXPIRED"
    if moneyness == "ITM" or confidence_pct >= 65:
        return "LIKELY_ASSIGNED"
    if catalyst_flag and confidence_pct >= 40:
        return "CATALYST_WARNING"
    if dte <= 7 and confidence_pct < 40:
        return "EXPIRING_WORTHLESS"
    if dte <= 14 and confidence_pct < 50:
        return "WIND_DOWN"
    return "HOLD"


def compute_next_leg(
    option: dict[str, Any],
    indicator: dict[str, Any],
    scores: dict[str, float],
    sgx_tickers: set[str],
    stock_positions: list[dict[str, Any]],
    all_scores: dict[str, dict[str, float]],  # all tickers' scores for ranking
) -> dict[str, Any]:
    """
    Produce a next-leg recommendation for an open option.

    option dict keys: ticker, right, strike, expiry, qty, account,
                     dte, confidence_pct, moneyness, adj_cost_basis,
                     catalyst_flag (derived below)
    indicator dict: full indicator bundle for the underlying
    scores dict: strategy scores for the underlying
    all_scores: {ticker: {strategy: score}} for cross-ticker comparison
    """
    ticker = option["ticker"]
    right = option["right"]
    strike = float(option["strike"])
    dte = int(option["dte"])
    confidence_pct = int(option.get("confidence_pct", 0))
    moneyness = option.get("moneyness", "?")
    account = option["account"]
    adj_cost = float(option.get("adj_cost_basis", 0))

    catalyst_flag = bool(indicator.get("catalyst_flag", False))
    current_status = _status_from_option(dte, confidence_pct, moneyness, catalyst_flag)

    underlying = float(indicator.get("close", 0))
    sigma_annual = float(indicator.get("volatility_annual", 0.4))

    result = {
        "ticker": ticker,
        "account": account,
        "current_right": right,
        "current_strike": strike,
        "current_expiry": option.get("expiry", ""),
        "current_dte": dte,
        "current_status": current_status,
        "next_action": "LET_EXPIRE",
        "next_strategy": "WAIT",
        "next_right": "",
        "next_strike": 0.0,
        "next_expiry": "",
        "next_dte": 0,
        "next_delta": 0.0,
        "next_premium": 0.0,
        "next_yield_pct": 0.0,
        "next_breakeven": 0.0,
        "recommendation": "",
        "reasoning": "",
        "confidence": 0,
    }

    # Determine the strategy the current option represents
    # Short put = CSP, short call on stock = CC
    stock_holdings = {p["ticker"]: p for p in stock_positions if p.get("account") == account}
    has_stock = ticker in stock_holdings and float(stock_holdings[ticker].get("qty", 0)) > 0

    qty = float(option.get("qty", 0))
    is_short = qty < 0
    if is_short and right == "P":
        current_strategy = "CSP"
    elif is_short and right == "C" and has_stock:
        current_strategy = "CC"
    elif is_short and right == "C" and not has_stock:
        current_strategy = "NAKED_CALL"
    else:
        current_strategy = "OTHER"

    # ========================================================================
    # Case A: HOLD — OTM, healthy, plenty of time. Stage next leg for preview.
    # ========================================================================
    if current_status == "HOLD":
        # Decide target delta adjusted for catalyst
        target_delta = TARGET_DELTA_CSP if current_strategy == "CSP" else TARGET_DELTA_CC
        if catalyst_flag:
            target_delta = max(0.10, target_delta - CATALYST_DELTA_ADJ)

        result["next_action"] = "LET_RUN"
        result["next_strategy"] = current_strategy
        result["recommendation"] = (
            f"Let ride. At expiry, scan next ~{target_delta:.2f}Δ {right} "
            f"on {ticker}."
        )
        result["reasoning"] = (
            f"Confidence {confidence_pct}%, {dte}d DTE, {moneyness}. "
            f"{'Catalyst detected — lower delta target.' if catalyst_flag else 'No warnings.'}"
        )
        result["confidence"] = 90 - confidence_pct  # high confidence in "let run" if assignment low
        return result

    # ========================================================================
    # Case B: EXPIRING_WORTHLESS — need to pick next leg now
    # ========================================================================
    if current_status in ("EXPIRING_WORTHLESS", "WIND_DOWN"):
        # Check if we should stay on this ticker or switch
        this_score = scores.get(current_strategy, 0.0)
        # Find best alternative for this strategy across all_scores
        best_alt_ticker = None
        best_alt_score = this_score
        for alt_ticker, alt_scores in all_scores.items():
            if alt_ticker == ticker:
                continue
            alt = alt_scores.get(current_strategy, 0.0)
            if alt > best_alt_score + SWITCH_SCORE_DELTA:
                best_alt_score = alt
                best_alt_ticker = alt_ticker

        # Decide target delta
        target_delta = TARGET_DELTA_CSP if current_strategy == "CSP" else TARGET_DELTA_CC
        if catalyst_flag:
            target_delta = max(0.10, target_delta - CATALYST_DELTA_ADJ)

        if this_score < MIN_SCORE_TO_STAY and best_alt_ticker:
            # Recommend switching
            result["next_action"] = "NEW_LEG"
            result["next_strategy"] = "SWITCH"
            result["recommendation"] = (
                f"After {ticker} expires, SWITCH to {best_alt_ticker} "
                f"(score {best_alt_score:+.0f} vs {this_score:+.0f} for {ticker})."
            )
            result["reasoning"] = (
                f"{current_strategy} score on {ticker} ({this_score:+.0f}) below "
                f"threshold ({MIN_SCORE_TO_STAY}). Better opportunity on "
                f"{best_alt_ticker}."
            )
            result["confidence"] = 70
            return result

        # Stay on same ticker — find next strike
        yahoo_sym = _fmt_yahoo_ticker(ticker, sgx_tickers)
        expiries = _find_monthly_expiries(yahoo_sym, TARGET_DTE_MIN, TARGET_DTE_MAX)
        if not expiries:
            result["next_action"] = "WAIT"
            result["recommendation"] = f"No {TARGET_DTE_MIN}-{TARGET_DTE_MAX}d expiries found for {ticker}."
            result["reasoning"] = "Option chain empty or outside DTE window."
            result["confidence"] = 40
            return result

        # Pick nearest to middle of window
        target_dte = (TARGET_DTE_MIN + TARGET_DTE_MAX) // 2
        best_exp = min(expiries, key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d").date() - date.today()).days - target_dte))
        best_dte = (datetime.strptime(best_exp, "%Y-%m-%d").date() - date.today()).days

        best = _find_best_strike(
            yahoo_sym, best_exp, right, target_delta, underlying, sigma_annual, best_dte,
        )
        if not best:
            result["next_action"] = "WAIT"
            result["recommendation"] = f"No suitable {target_delta:.2f}Δ strike found."
            result["reasoning"] = "Option chain at expiry empty or illiquid."
            result["confidence"] = 40
            return result

        result["next_action"] = "NEW_LEG"
        result["next_strategy"] = current_strategy
        result["next_right"] = right
        result["next_strike"] = best["strike"]
        result["next_expiry"] = best["expiry"].replace("-", "")
        result["next_dte"] = best_dte
        result["next_delta"] = best["delta"]
        result["next_premium"] = best["premium"]
        result["next_yield_pct"] = best["annual_yield_pct"]
        result["next_breakeven"] = best["breakeven"]

        # For CC: never sell below adjusted cost basis
        if current_strategy == "CC" and adj_cost > 0 and best["strike"] < adj_cost:
            result["recommendation"] = (
                f"⚠ {target_delta:.2f}Δ strike ${best['strike']:.2f} is BELOW your "
                f"adjusted basis ${adj_cost:.2f}. Consider higher strike or different ticker."
            )
            result["confidence"] = 40
        else:
            result["recommendation"] = (
                f"Sell {current_strategy} ${best['strike']:.2f}{right} exp {best['expiry']} "
                f"(~{best['delta_mag']:.2f}Δ, ${best['premium']:.2f}/share, "
                f"{best['annual_yield_pct']:.0f}% ann. yield)"
            )
            result["confidence"] = min(90, 50 + int(this_score))

        dte_note = f"{best_dte}d DTE" if best_dte else ""
        score_note = f"{current_strategy} score {this_score:+.0f}"
        cat_note = ", catalyst detected (lower delta)" if catalyst_flag else ""
        result["reasoning"] = f"{score_note}, {dte_note}{cat_note}"
        return result

    # ========================================================================
    # Case C: LIKELY_ASSIGNED — plan post-assignment
    # ========================================================================
    if current_status == "LIKELY_ASSIGNED":
        if current_strategy == "CSP":
            # About to be assigned stock — plan first CC above adjusted basis
            post_adj_basis = strike - float(option.get("credit", 0))
            result["next_action"] = "PLAN_POST_ASSIGNMENT"
            result["next_strategy"] = "CC"
            result["next_right"] = "C"
            # Target CC strike slightly above post-adj basis
            target_cc_strike = post_adj_basis * 1.03  # 3% above basis as starting point
            result["next_strike"] = round(target_cc_strike, 2)
            result["recommendation"] = (
                f"Likely assigned at ${strike:.2f}. Post-adj basis ~${post_adj_basis:.2f}. "
                f"Plan first CC at or above ~${target_cc_strike:.2f}."
            )
            result["reasoning"] = (
                f"Confidence {confidence_pct}%, {moneyness}. Wheel rotates from CSP → CC."
            )
            result["confidence"] = 75
            return result

        if current_strategy == "CC":
            # About to be called away — plan next CSP on same ticker or switch
            # Free cash after assignment: 100 × strike
            this_csp_score = scores.get("CSP", 0.0)
            # Find best CSP alternative
            best_alt_csp = None
            best_alt_score = this_csp_score
            for alt_ticker, alt_scores in all_scores.items():
                if alt_ticker == ticker:
                    continue
                alt = alt_scores.get("CSP", 0.0)
                if alt > best_alt_score + SWITCH_SCORE_DELTA:
                    best_alt_score = alt
                    best_alt_ticker_val = alt_ticker
                    best_alt_csp = alt_ticker

            result["next_action"] = "PLAN_POST_ASSIGNMENT"
            result["next_strategy"] = "CSP"
            result["next_right"] = "P"
            if best_alt_csp and this_csp_score < MIN_SCORE_TO_STAY:
                result["recommendation"] = (
                    f"Likely called away at ${strike:.2f}. Consider rotating capital to "
                    f"{best_alt_csp} CSP (score {best_alt_score:+.0f})."
                )
                result["next_strategy"] = "SWITCH"
            else:
                result["recommendation"] = (
                    f"Likely called away at ${strike:.2f}. Re-enter with new CSP on {ticker} "
                    f"(score {this_csp_score:+.0f})."
                )
            result["reasoning"] = (
                f"Confidence {confidence_pct}% of call assignment, {moneyness}."
            )
            result["confidence"] = 70
            return result

    # ========================================================================
    # Case D: CATALYST_WARNING — lower delta or skip
    # ========================================================================
    if current_status == "CATALYST_WARNING":
        result["next_action"] = "REDUCE_RISK"
        result["next_strategy"] = current_strategy
        target_delta = 0.15  # more conservative
        result["recommendation"] = (
            f"⚠ Catalyst on {ticker} (confidence {confidence_pct}%). "
            f"Consider closing or rolling to {target_delta:.2f}Δ at next expiry."
        )
        result["reasoning"] = (
            f"Catalyst detected (vol regime elevated). Current position may breach if move continues."
        )
        result["confidence"] = 60
        return result

    # Expired case
    if current_status == "EXPIRED":
        result["next_action"] = "REVIEW"
        result["recommendation"] = f"Position expired. Review outcome and plan next cycle."
        result["reasoning"] = "DTE <= 0"
        result["confidence"] = 100
        return result

    return result
