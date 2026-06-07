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


# ── Ticker → bucket map + per-ticker option-eligibility gates ────────────────
# Single source of truth for "which wheel discipline applies to this ticker".
# Unknown tickers default to 'spec_growth' (the most permissive natural wheel
# target — CC- and CSP-eligible), so discovery-universe names are never
# over-suppressed; only KNOWN core/blue_chip/leveraged_etf/lottery names get
# gated. Promoted here from options_yield_screener so every scanner shares it.
TICKER_BUCKET: dict[str, str] = {
    # core (no CCs ever — never wheel away the compounder)
    "SCHD": "core", "SPY": "core", "VOO": "core", "QQQ": "core",
    "VTI": "core", "VEA": "core", "VWO": "core", "BND": "core",
    # blue_chip (no CCs unless strike ≥ 115% cost — scanners lack per-user cost
    # basis, so block CC entirely here; the brain can override with cost info)
    "AAPL": "blue_chip", "MSFT": "blue_chip", "GOOGL": "blue_chip",
    "GOOG": "blue_chip", "AMZN": "blue_chip", "META": "blue_chip",
    "NFLX": "blue_chip", "JPM": "blue_chip", "V": "blue_chip",
    "MA": "blue_chip", "JNJ": "blue_chip", "PG": "blue_chip",
    "KO": "blue_chip", "BRK-B": "blue_chip",
    # leveraged_etf (no CCs/CSPs ever — daily reset + assignment compounds)
    "TQQQ": "leveraged_etf", "SQQQ": "leveraged_etf",
    "SSO": "leveraged_etf", "UPRO": "leveraged_etf",
    "SOXL": "leveraged_etf", "TNA": "leveraged_etf",
    # commodity_etf (CCs OK on strength)
    "GLD": "commodity_etf", "SLV": "commodity_etf", "GDX": "commodity_etf",
    "GDXJ": "commodity_etf", "USO": "commodity_etf", "UNG": "commodity_etf",
    "DBA": "commodity_etf", "CPER": "commodity_etf", "GLDM": "commodity_etf",
    # quality_growth (CCs OK)
    "AMD": "quality_growth", "NVDA": "quality_growth",
    # spec_growth (CCs OK — the natural CC pool)
    "F": "spec_growth", "T": "spec_growth", "BAC": "spec_growth",
    "WFC": "spec_growth", "INTC": "spec_growth", "MU": "spec_growth",
    "PYPL": "spec_growth", "U": "spec_growth", "RBLX": "spec_growth",
    "SOFI": "spec_growth", "RIVN": "spec_growth", "AFRM": "spec_growth",
    "SHOP": "spec_growth", "COIN": "spec_growth", "TSLA": "spec_growth",
    "OPEN": "spec_growth", "RDDT": "spec_growth", "PLTR": "spec_growth",
    "SQ": "spec_growth", "HIMS": "spec_growth", "SBET": "spec_growth",
    # lottery (CSPs blocked — assignment risk too high; CCs OK)
    "BBAI": "lottery", "BTBT": "lottery", "RCAT": "lottery", "BYND": "lottery",
    # defensive ETFs (treat as commodity_etf-like — CCs OK on strength)
    "XLV": "commodity_etf", "XLP": "commodity_etf", "XLU": "commodity_etf",
    "VHT": "commodity_etf", "VDC": "commodity_etf", "VPU": "commodity_etf",
    "ITA": "commodity_etf", "KRE": "commodity_etf",
    # volatility products — never wheel
    "VIXM": "leveraged_etf", "UVXY": "leveraged_etf", "SVXY": "leveraged_etf",
}


def bucket_for(ticker: str) -> str:
    """Bucket name for a ticker. Defaults to 'spec_growth' (most permissive
    natural wheel target) when unknown."""
    return TICKER_BUCKET.get(ticker.upper(), "spec_growth")


def cc_blocked_by_bucket(ticker: str) -> tuple[bool, str]:
    """(blocked, reason). True if CC is NOT eligible for this ticker's bucket
    (core / blue_chip / leveraged_etf). blue_chip blocks here because scanners
    don't track per-user cost basis (need strike >= 115% cost)."""
    bucket = bucket_for(ticker)
    if bucket == "blue_chip":
        return True, "CC blocked: blue_chip (need strike >= 115% cost)"
    if not CC_ELIGIBLE_BUCKETS.get(bucket, True):
        return True, f"CC blocked: {bucket} not CC-eligible"
    return False, bucket


def csp_blocked_by_bucket(ticker: str) -> tuple[bool, str]:
    """(blocked, reason). True if CSP is NOT eligible for this ticker's bucket
    (lottery / leveraged_etf)."""
    bucket = bucket_for(ticker)
    if not CSP_ELIGIBLE_BUCKETS.get(bucket, True):
        return True, f"CSP blocked: {bucket} not CSP-eligible"
    return False, bucket


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
    # RSI + volume gates removed — the brain already filtered for quality,
    # and these were blocking clean entries on momentum moves.
    "require_above_sma50":         False,# Sometimes you ENTER on SMA50 reclaim
    "skip_if_macd_bear_cross_24h": False,# Disabled — brain handles timing
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
