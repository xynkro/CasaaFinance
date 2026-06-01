"""
option_pnl.py — Single-source realistic option P&L settlement model.

ONE settlement core, two entry points:

  • settle_*  — REAL trade P&L given the ACTUAL strike + premium collected.
                Used by scripts/signal_feedback.py on live scan_results rows
                (the scanner records the real credit and strike).

  • *_pnl_pct — BSM-SYNTHESIZED strike + premium from a realized-vol proxy,
                then settled. Used by scripts/backtest_scoring.py, which has no
                option chain and must approximate the strike/premium it would
                have sold.

Both paths settle at expiry (European, no early assignment), NET the premium,
CAP the payoff at the strike, and charge a flat round-trip friction. P&L is a
% of each strategy's natural notional so CSP and CC are directly comparable:

  CSP → % of the cash-secured strike   (capital committed = strike × 100)
  CC  → % of the share cost basis (entry)

Sign convention is the whole point: a profitable trade is POSITIVE and a losing
trade is NEGATIVE, premium included. This replaces the old raw stock-return
proxy in signal_feedback that omitted the premium and could log a profitable
covered call as a loss (and vice-versa).
"""
from __future__ import annotations

import math

_RF = 0.04          # risk-free rate
_RT_COST = 0.02     # round-trip commission + slippage, $/share


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bsm_put(S: float, K: float, T: float, sigma: float, r: float = _RF) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _bsm_call(S: float, K: float, T: float, sigma: float, r: float = _RF) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


# ── Settlement core (REAL strike + premium) ──────────────────────────────────

def csp_settle_pct(
    strike: float, premium: float, exit_price: float, rt_cost: float = _RT_COST,
) -> float:
    """Realized cash-secured-put P&L as a % of the cash-secured strike.

    Keep the FULL premium if the put expires OTM (exit >= strike); otherwise the
    premium minus the assignment loss (strike - exit). Round-trip cost netted.
    Premium-inclusive, so the sign tracks profitability:
        OTM expiry          → +premium/strike            (a win)
        assigned, shallow   → premium > loss → positive  (a win)
        assigned, deep      → loss > premium → negative   (a loss)
    """
    if strike <= 0:
        return 0.0
    if exit_price >= strike:
        pnl = premium - rt_cost
    else:
        pnl = premium - (strike - exit_price) - rt_cost
    return pnl / strike * 100.0


def cc_settle_pct(
    entry: float, strike: float, premium: float, exit_price: float,
    rt_cost: float = _RT_COST,
) -> float:
    """Realized covered-call P&L as a % of the share cost basis (entry).

    Stock move CAPPED at the strike when called away, PLUS the premium, minus
    round-trip cost. Premium-inclusive, so:
        called away above cost (OTM call) → capped gain + premium → POSITIVE
            (this is the max-profit outcome, NOT a loss — the old proxy mislabelled
             it because it looked only at assignment, not P&L)
        sideways-down, premium covers drop → POSITIVE  (the common CC win)
        down more than premium             → NEGATIVE  (a real loss, even though
             the call expired worthless and the shares were kept)
    """
    if entry <= 0:
        return 0.0
    capped_exit = min(exit_price, strike)   # shares called away above the strike
    pnl = (capped_exit - entry) + premium - rt_cost
    return pnl / entry * 100.0


# ── Synthesized strike + premium (no chain — backtest only) ──────────────────

def csp_pnl_pct(entry: float, exit_price: float, sigma: float, hold_days: int) -> float:
    """CSP P&L as % of the cash-secured notional (strike). Sells a ~0.25Δ put
    (≈0.67σ OTM over the hold), prices it via BSM from the realized-vol proxy,
    then settles. Underlying-driven approximation (no IV smile, no early
    assignment) but real option economics, not a flat 2%."""
    T = max(hold_days / 365.0, 1e-6)
    sigma = sigma if sigma > 0 else 0.4
    otm = 0.67 * sigma * math.sqrt(T)
    strike = entry * (1 - otm)
    prem = _bsm_put(entry, strike, T, sigma)
    return csp_settle_pct(strike, prem, exit_price)


def cc_pnl_pct(entry: float, exit_price: float, sigma: float, hold_days: int) -> float:
    """Covered-call P&L as % of shares cost (entry). Sells a ~0.25Δ call;
    P&L = stock move (capped at the strike when called away) + premium − cost."""
    T = max(hold_days / 365.0, 1e-6)
    sigma = sigma if sigma > 0 else 0.4
    otm = 0.67 * sigma * math.sqrt(T)
    strike = entry * (1 + otm)
    prem = _bsm_call(entry, strike, T, sigma)
    return cc_settle_pct(entry, strike, prem, exit_price)
