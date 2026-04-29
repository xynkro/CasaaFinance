"""
trading_rules.py — Baked-in trading discipline rules referenced by every
brain (Daily Brief, WSR Lite, WSR Monday) so the model doesn't have to
invent thresholds each session.

These are conservative defaults grounded in:
  - Singapore no-CGT environment (favours holding winners, careful loss-cutting)
  - Swing trading horizon (days to weeks)
  - Mixed wheel + directional book (CSP/CC + selective stock holds)
  - Two-account split (Caspar = small/spec, Sarah = larger/quality)

Every value here is opinionated. Override only with explicit reasoning logged
in the WSR.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ── POSITION SIZING (% of net liquidation per single position) ───────────────
# Why: edge erodes fast as concentration rises; max-allocation caps protect
# against single-name surprises (earnings gap, geopolitics, fraud).
SIZING_LIMITS_PCT_NETLIQ = {
    "core":           15.0,  # SCHD, SPY core, broad ETFs
    "blue_chip":      10.0,  # AAPL, MSFT, GOOGL, MA, V, JPM
    "quality_growth":  8.0,  # AMD, NVDA, META, NFLX
    "spec_growth":     5.0,  # OPEN, RDDT, SOFI, RKLB
    "lottery":         2.0,  # BBAI, BTBT, RCAT — losers acceptable
    "leveraged_etf":   4.0,  # TQQQ, SSO, UPRO — daily reset = compounding decay
    "commodity_etf":   8.0,  # SLV, GLD, GLDM
}

# Combined cap on all leveraged ETFs (TQQQ + SSO + …) regardless of individual.
LEVERAGED_ETF_AGGREGATE_CAP_PCT = 8.0


# ── STOP LOSSES (% from cost basis; non-negotiable for spec/lottery) ─────────
# Singapore no-CGT note: no tax-loss harvesting, but cutting losers fast
# preserves capital for compounding winners. Hard stops on spec/lottery,
# softer rules on core/blue chip (mean-reversion dominant).
STOP_LOSS_PCT = {
    "core":           None,  # No mechanical stop — fundamentals + decision queue
    "blue_chip":     -15.0,
    "quality_growth":-15.0,
    "spec_growth":   -20.0,
    "lottery":       -30.0,  # Wide because volatility, but small position sizes
    "leveraged_etf": -10.0,  # Below SMA200 OR -10% — whichever first
    "commodity_etf": -15.0,
}

# Time stop: if thesis hasn't played out in N days, exit regardless of price.
# Stops "dead money" sitting in positions waiting for a catalyst that never came.
TIME_STOP_DAYS = {
    "swing_thesis":     60,   # Specific thesis (e.g. earnings re-rate)
    "wheel_assignment": 90,   # Held a CSP that got assigned — give it 3mo
    "lottery":          45,   # Spec lottery — fish or cut bait
    "core":             None, # Core holds are forever
}


# ── PROFIT TAKING (trim ladder so you book wins on the way up) ───────────────
# Why: behavioural finance — most traders give back gains by holding too long.
# Pre-committed trim levels remove the discretion.
TRIM_LADDERS = {
    # On (gain_pct → trim_pct of position)
    "core":            [],  # Don't trim core
    "blue_chip":       [(50, 25), (100, 33)],
    "quality_growth":  [(40, 25), (80, 33), (150, 50)],
    "spec_growth":     [(50, 33), (100, 50), (200, 75)],
    "lottery":         [(100, 50), (200, 100)],  # 100% gain → trim half, 2x → all out
    "leveraged_etf":   [(15, 25), (25, 50), (40, 100)],  # Aggressive — decay risk
    "commodity_etf":   [(30, 33), (60, 50)],
}


# ── LEVERAGED ETF DISCIPLINE (TQQQ, SSO, UPRO, etc.) ─────────────────────────
# Daily-reset products compound losses worse than gains; they REQUIRE rules.
LEVERAGED_ETF_RULES = {
    "max_holding_days":      30,   # >30 days: decay starts dominating
    "trim_above_sma50_pct":  10,   # Above SMA50 by 10% → trim 25%
    "exit_below_sma200":     True, # Cross below 200d → full exit, no questions
    "no_add_above_atm_iv":   True, # Don't add when VIX > 25 (whipsaw risk)
    "reentry_block_days":    14,   # After exit, can't re-enter for 14 days
}


# ── OPTIONS WRITING ELIGIBILITY (per bucket) ─────────────────────────────────
# Critical rule: don't wheel core dividend compounders or blue-chip holds.
# Why: writing a CC means you accept the position can be called away. For
# SCHD (the income engine you're building toward 100 shares), being called
# away INTERRUPTS the compounding plan and triggers re-entry friction.
# Same for AAPL / MSFT / GOOGL etc. — long-term holds where assignment is
# net-negative even with premium income.
#
# Wheeling is appropriate on tickers you're ambivalent about owning long-term:
# spec_growth, lottery names where you'd happily exit at the strike.
CC_ELIGIBLE_BUCKETS = {
    "core":           False,  # SCHD, broad ETFs — never wheel away the compounder
    "blue_chip":      False,  # AAPL, MSFT, GOOGL — only DEEP OTM if at all
    "quality_growth": True,   # AMD, NVDA, META — OK if strike >> cost basis
    "spec_growth":    True,   # OPEN, RDDT, SOFI — natural CC candidates
    "lottery":        True,   # BBAI, BTBT — ride premium, exit happy
    "leveraged_etf":  False,  # TQQQ, SSO — decay + assignment compounds losses
    "commodity_etf":  True,   # SLV, GLD — wheelable on strength
}
# For blue_chip exception: if you really want to write CCs, only on strikes
# >= 1.15× cost basis (15% above) where assignment lets you book a chunky
# capital gain you'd accept. Below that, just hold the stock.
CC_BLUE_CHIP_MIN_STRIKE_PCT_OF_COST = 1.15

# CSP eligibility: opposite intuition — get paid to maybe BUY at a price
# you'd happily buy at. Quality/blue-chip are the BEST CSP targets because
# assignment = "I got paid to acquire SCHD/AAPL at the price I wanted".
CSP_ELIGIBLE_BUCKETS = {
    "core":           True,   # CSP on SCHD = paid to accumulate to 100 shares
    "blue_chip":      True,   # CSP on AAPL = paid to maybe own at fair value
    "quality_growth": True,
    "spec_growth":    True,
    "lottery":        False,  # Don't write puts on lottery — assignment risk too high
    "leveraged_etf":  False,  # Decay risk on owning leveraged ETFs
    "commodity_etf":  True,
}


def cc_allowed(bucket: str, strike: float = 0, cost_basis: float = 0) -> tuple[bool, str]:
    """Return (allowed, reason). For blue_chip, also enforces strike >= 115% of cost."""
    if bucket not in CC_ELIGIBLE_BUCKETS:
        return False, f"Unknown bucket: {bucket}"
    if not CC_ELIGIBLE_BUCKETS[bucket]:
        return False, f"CC not eligible on {bucket} — assignment would interrupt thesis"
    if bucket == "blue_chip" and cost_basis > 0:
        min_strike = cost_basis * CC_BLUE_CHIP_MIN_STRIKE_PCT_OF_COST
        if strike < min_strike:
            return False, (f"Blue-chip CC requires strike ≥ ${min_strike:.2f} "
                           f"(115% of ${cost_basis:.2f} cost). Got ${strike:.2f}.")
    return True, "OK"


def csp_allowed(bucket: str) -> tuple[bool, str]:
    if bucket not in CSP_ELIGIBLE_BUCKETS:
        return False, f"Unknown bucket: {bucket}"
    if not CSP_ELIGIBLE_BUCKETS[bucket]:
        return False, f"CSP not eligible on {bucket}"
    return True, "OK"


# ── OPTIONS WRITING RULES ────────────────────────────────────────────────────

# Cash-Secured Puts — paid to maybe own quality
CSP_RULES = {
    "dte_min":                 25,
    "dte_max":                 45,
    "dte_ideal":               35,
    "delta_min":               0.15,
    "delta_max":               0.28,
    "delta_ideal":             0.20,
    "iv_rank_min":             30,    # Don't sell premium when IV is dead
    "min_annual_yield_pct":    15,    # Below 15%/yr — capital better elsewhere
    "max_strike_otm_pct":      18,    # No selling deep OTM puts (no premium)
    "min_strike_otm_pct":      2,     # No ATM either (assignment risk)
    "skip_if_earnings_within": 10,    # Days — IV crush risk
    "skip_if_below_support":   True,  # Don't catch falling knives
    # Quality gate: only on stocks you'd be HAPPY to own at strike
    "quality_only":            True,
}

# Covered Calls — collect yield on stocks you already own 100+ shares of
CC_RULES = {
    "dte_min":                 25,
    "dte_max":                 45,
    "dte_ideal":               35,
    "delta_min":               0.15,
    "delta_max":               0.30,
    "delta_ideal":             0.22,
    "iv_rank_min":             35,
    "min_annual_yield_pct":    12,
    "max_strike_otm_pct":      10,    # Higher = no premium
    "min_strike_otm_pct":      2,     # Don't write ITM (called away guaranteed)
    "skip_if_earnings_within": 7,
    # Strike must be ≥ cost basis: don't lock in a loss
    "strike_min_vs_cost":      1.00,
    "strike_target_vs_cost":   1.08,  # 8% above cost basis as ideal
}

# Roll triggers (defensive)
ROLL_RULES = {
    "csp_roll_at_delta":         0.45,  # Test → roll out and down
    "cc_roll_at_delta":          0.40,  # Test → roll up and out (capture credit)
    "take_profit_at_pct":        50,    # 50% premium captured → close, redeploy
    "roll_dte_threshold":        14,    # If <14 DTE remaining + tested → must roll
    "max_rolls_per_position":    3,     # After 3 rolls — accept assignment
}


# ── REGIME-AWARE LEVERAGE CAPS (% of net liq in beta-leveraged exposure) ─────
# As regime turns risk-off, total leverage MUST come down. Hard ceilings.
REGIME_LEVERAGE_CAPS_PCT = {
    "bull_early_cycle":  60,  # Embrace momentum, full size
    "bull_mid_cycle":    50,
    "bull_late_cycle":   35,  # ← current regime per WSR
    "topping":           20,
    "ranging":           30,
    "bear":              10,  # Cash-heavy, only deep-value adds
    "panic":              5,
}

# Cash floor — minimum cash % to keep dry powder for opportunities
CASH_FLOOR_PCT_BY_REGIME = {
    "bull_early_cycle":   5,
    "bull_mid_cycle":    10,
    "bull_late_cycle":   15,
    "topping":           25,
    "ranging":           20,
    "bear":              40,
    "panic":             50,
}


# ── CATALYST AVOIDANCE (don't enter into binary events) ──────────────────────
CATALYST_BLACKOUTS = {
    "earnings_no_new_entry_days":   5,   # Inside 5d of earnings → no fresh entry
    "earnings_no_options_write":    3,   # Inside 3d → no premium selling (IV crush)
    "fomc_size_reduction_pct":      50,  # Day-of FOMC → 50% normal size
    "cpi_size_reduction_pct":       33,
    "no_new_swings_into_holiday":   True,
}


# ── DECISION QUEUE GATING (when is an entry "actionable") ────────────────────
# A queue entry only fires when ALL of these align — prevents FOMO chasing.
ENTRY_GATING = {
    "max_pct_above_entry_to_buy":  3.0,  # If >3% above stated entry → wait/skip
    "rsi_max_for_buy":             65,   # Not stretched
    "min_volume_ratio_to_avg":     0.7,  # Not on no-volume drift
    "require_above_sma50":         False,# Sometimes you ENTER on SMA50 reclaim
    "skip_if_macd_bear_cross_24h": True, # Wait for confirmation
}


# ── WHEEL DISCIPLINE ─────────────────────────────────────────────────────────
WHEEL_RULES = {
    # Only wheel on stocks you'd own 100 shares of for 12+ months at this price
    "min_holding_horizon_months": 12,
    # Total premium captured must beat dividend yield + 8%
    "min_premium_yield_above_div": 8.0,
    # Don't wheel below SMA200 (downtrend = unlimited assignment downside)
    "no_wheel_below_sma200":      True,
    # Earnings stocks: skip the cycle covering earnings entirely
    "no_wheel_through_earnings":  True,
}


# ── ACCOUNT-SPECIFIC POSTURES ────────────────────────────────────────────────
# Caspar (small, USD): aggressive growth + spec, willing to take losses
# Sarah (large, SGD-denominated): quality + income, capital preservation first
ACCOUNT_POSTURE = {
    "caspar": {
        "max_spec_lottery_pct":   25,
        "max_leveraged_etf_pct":  10,
        "preferred_strategies":   ["swing_directional", "lottery_runner"],
        "options_role":           "aggressive_csp_only_when_high_conviction",
    },
    "sarah": {
        "max_spec_lottery_pct":    5,
        "max_leveraged_etf_pct":   3,
        "preferred_strategies":    ["wheel_quality", "buy_dip_blue_chip", "csp_income"],
        "options_role":            "core_income_engine",
    },
}


# ── HELPER FUNCTIONS — brains call these for sanity-check decisions ──────────

@dataclass
class PositionContext:
    ticker: str
    bucket: Literal[
        "core", "blue_chip", "quality_growth", "spec_growth",
        "lottery", "leveraged_etf", "commodity_etf"
    ]
    qty: float
    avg_cost: float
    current_price: float
    weight_pct: float    # As % of net liq
    days_held: int
    account: Literal["caspar", "sarah"]


def position_action(p: PositionContext, regime: str = "bull_late_cycle") -> dict:
    """
    Return action for a position given current rules.
    Output: {action, reason, urgency} where action ∈
      HOLD | TRIM_X% | EXIT | ADD_OK | REVIEW
    """
    upl_pct = (p.current_price - p.avg_cost) / p.avg_cost * 100

    # Stop check
    stop = STOP_LOSS_PCT.get(p.bucket)
    if stop is not None and upl_pct <= stop:
        return {"action": "EXIT", "reason": f"Hit -{abs(stop):.0f}% stop (UPL {upl_pct:+.1f}%)", "urgency": "URGENT"}

    # Time stop check
    if p.bucket == "leveraged_etf" and p.days_held > LEVERAGED_ETF_RULES["max_holding_days"]:
        return {"action": "TRIM_50%", "reason": f"Held {p.days_held}d > 30d leverage decay window", "urgency": "HIGH"}

    # Sizing check
    cap = SIZING_LIMITS_PCT_NETLIQ[p.bucket]
    if p.weight_pct > cap * 1.2:  # 20% over cap
        excess = p.weight_pct - cap
        return {"action": f"TRIM_{int(excess/p.weight_pct*100)}%", "reason": f"Weight {p.weight_pct:.1f}% > {cap}% cap by 20%+", "urgency": "MEDIUM"}

    # Profit-take ladder
    for gain_threshold, trim_pct in TRIM_LADDERS.get(p.bucket, []):
        if upl_pct >= gain_threshold:
            return {"action": f"TRIM_{trim_pct}%", "reason": f"Hit +{gain_threshold}% trim ladder", "urgency": "MEDIUM"}

    # Regime check
    leverage_cap = REGIME_LEVERAGE_CAPS_PCT.get(regime, 50)
    if p.bucket in ("leveraged_etf", "spec_growth") and p.weight_pct > leverage_cap / 4:
        return {"action": "REVIEW", "reason": f"In {regime} — leverage cap is {leverage_cap}%", "urgency": "LOW"}

    return {"action": "HOLD", "reason": f"Within rules (UPL {upl_pct:+.1f}%, weight {p.weight_pct:.1f}%)", "urgency": "NONE"}


def csp_qualifies(strike: float, premium: float, dte: int, iv_rank: float,
                  underlying: float, days_to_earnings: int = 999,
                  underlying_above_sma200: bool = True) -> tuple[bool, str]:
    """Check if a CSP candidate meets all CSP_RULES gates."""
    r = CSP_RULES
    if dte < r["dte_min"] or dte > r["dte_max"]:
        return False, f"DTE {dte} outside [{r['dte_min']},{r['dte_max']}]"
    otm_pct = (underlying - strike) / underlying * 100
    if otm_pct < r["min_strike_otm_pct"]:
        return False, f"Only {otm_pct:.1f}% OTM (min {r['min_strike_otm_pct']}%)"
    if otm_pct > r["max_strike_otm_pct"]:
        return False, f"{otm_pct:.1f}% OTM (max {r['max_strike_otm_pct']}%)"
    if iv_rank < r["iv_rank_min"]:
        return False, f"IV rank {iv_rank:.0f} < {r['iv_rank_min']}"
    annual_yield = (premium / strike) * (365 / dte) * 100
    if annual_yield < r["min_annual_yield_pct"]:
        return False, f"Yield {annual_yield:.0f}%/yr < {r['min_annual_yield_pct']}%"
    if days_to_earnings < r["skip_if_earnings_within"]:
        return False, f"Earnings in {days_to_earnings}d"
    if r["skip_if_below_support"] and not underlying_above_sma200:
        return False, "Below SMA200 (downtrend)"
    return True, f"Qualifies — {annual_yield:.0f}%/yr, {otm_pct:.1f}% OTM"


def cc_qualifies(strike: float, premium: float, dte: int, iv_rank: float,
                 underlying: float, cost_basis: float,
                 days_to_earnings: int = 999) -> tuple[bool, str]:
    """Check if a Covered Call candidate passes CC_RULES."""
    r = CC_RULES
    if dte < r["dte_min"] or dte > r["dte_max"]:
        return False, f"DTE {dte} outside range"
    if strike < cost_basis * r["strike_min_vs_cost"]:
        return False, f"Strike ${strike:.2f} below cost basis (locks loss)"
    otm_pct = (strike - underlying) / underlying * 100
    if otm_pct < r["min_strike_otm_pct"] or otm_pct > r["max_strike_otm_pct"]:
        return False, f"{otm_pct:.1f}% OTM out of [{r['min_strike_otm_pct']},{r['max_strike_otm_pct']}]"
    if iv_rank < r["iv_rank_min"]:
        return False, f"IV rank {iv_rank:.0f} too low"
    annual_yield = (premium / underlying) * (365 / dte) * 100
    if annual_yield < r["min_annual_yield_pct"]:
        return False, f"Yield {annual_yield:.0f}%/yr too thin"
    if days_to_earnings < r["skip_if_earnings_within"]:
        return False, f"Earnings in {days_to_earnings}d"
    return True, f"Qualifies — {annual_yield:.0f}%/yr at {otm_pct:.1f}% OTM"


def regime_max_leverage(regime: str) -> float:
    """% of net liq allowed in leveraged + spec exposure for current regime."""
    return REGIME_LEVERAGE_CAPS_PCT.get(regime, 35.0)


def regime_cash_floor(regime: str) -> float:
    """Minimum cash % to maintain for current regime."""
    return CASH_FLOOR_PCT_BY_REGIME.get(regime, 15.0)


# ── EXPORT ALL RULES AS A SINGLE DICT FOR THE BRAIN'S CONTEXT ────────────────
def all_rules_summary() -> dict:
    """Return every rule as a single dict — pass this to the synthesis brain
    so it has explicit thresholds instead of inventing them."""
    return {
        "sizing_pct_netliq":           SIZING_LIMITS_PCT_NETLIQ,
        "leveraged_etf_aggregate_cap": LEVERAGED_ETF_AGGREGATE_CAP_PCT,
        "stop_loss_pct":               STOP_LOSS_PCT,
        "time_stop_days":              TIME_STOP_DAYS,
        "trim_ladders":                TRIM_LADDERS,
        "leveraged_etf_rules":         LEVERAGED_ETF_RULES,
        "cc_eligible_buckets":         CC_ELIGIBLE_BUCKETS,
        "csp_eligible_buckets":        CSP_ELIGIBLE_BUCKETS,
        "cc_blue_chip_min_strike_pct_of_cost": CC_BLUE_CHIP_MIN_STRIKE_PCT_OF_COST,
        "csp_rules":                   CSP_RULES,
        "cc_rules":                    CC_RULES,
        "roll_rules":                  ROLL_RULES,
        "regime_leverage_caps_pct":    REGIME_LEVERAGE_CAPS_PCT,
        "cash_floor_pct_by_regime":    CASH_FLOOR_PCT_BY_REGIME,
        "catalyst_blackouts":          CATALYST_BLACKOUTS,
        "entry_gating":                ENTRY_GATING,
        "wheel_rules":                 WHEEL_RULES,
        "account_posture":             ACCOUNT_POSTURE,
    }
