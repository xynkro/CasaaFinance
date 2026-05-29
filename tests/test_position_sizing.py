"""Tests for src/position_sizing.py — risk profiles + contract sizing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.position_sizing import (  # noqa: E402
    PROFILES,
    regime_multiplier,
    estimate_bpr_per_contract,
    size_candidate,
)


# ── BPR estimation ─────────────────────────────────────────────────────────

def test_bpr_csp_margin_regt():
    # $20 underlying, $18 put, $0.50 credit. Reg-T = max(0.2*20-2+0.5, 0.1*18+0.5)*100
    #   = max(2.5, 2.3)*100 = 250
    bpr = estimate_bpr_per_contract("CSP", strike=18, underlying=20, premium=0.50, is_margin=True)
    assert abs(bpr - 250.0) < 1.0


def test_bpr_csp_cash_secured():
    # Cash account: full notional = strike * 100
    bpr = estimate_bpr_per_contract("CSP", strike=18, underlying=20, premium=0.50, is_margin=False)
    assert bpr == 1800.0


def test_bpr_cc_margin_uses_call_otm():
    # $20 underlying, $22 call (OTM by 2), $0.40 credit
    #   max(0.2*20 - 2 + 0.4, 0.1*22 + 0.4)*100 = max(2.4, 2.6)*100 = 260
    bpr = estimate_bpr_per_contract("CC", strike=22, underlying=20, premium=0.40, is_margin=True)
    assert abs(bpr - 260.0) < 1.0


def test_bpr_defined_risk_is_max_loss():
    # PCS width 5, net credit 1.5 -> max loss = (5 - 1.5) * 100 = 350
    bpr = estimate_bpr_per_contract("PCS", strike=95, underlying=100, premium=1.5, width=5)
    assert bpr == 350.0


def test_bpr_debit_strategy_is_premium_paid():
    bpr = estimate_bpr_per_contract("PMCC", strike=0, underlying=100, premium=8.0)
    assert bpr == 800.0


# ── Regime multiplier ───────────────────────────────────────────────────────

def test_regime_aggressive():
    assert regime_multiplier(18, True, "aggressive") == 1.0
    assert regime_multiplier(27, True, "aggressive") == 0.5     # VIX 25-30
    assert regime_multiplier(32, True, "aggressive") == 0.0     # VIX>30 halt
    assert regime_multiplier(15, False, "aggressive") == 0.0    # SPX<200dma halt


def test_regime_balanced():
    assert regime_multiplier(18, True, "balanced") == 1.0
    assert regime_multiplier(27, True, "balanced") == 0.66      # VIX>25
    assert regime_multiplier(32, True, "balanced") == 0.5       # VIX>30
    assert regime_multiplier(15, False, "balanced") == 0.5      # SPX<200dma
    assert regime_multiplier(32, False, "balanced") == 0.33     # both


# ── Sizing: Caspar's real account ($9,319 NLV / $4,471 excess liquidity) ─────

CASPAR_NLV = 9319.03
CASPAR_EXCESS = 4471.03


def test_caspar_per_name_cap_binds_on_small_account():
    # $20 underlying CSP, BPR ~$250. per-name cap = 5% * 9319 = $466 -> 1 contract.
    r = size_candidate(
        strategy="CSP", strike=18, underlying=20, premium=0.50,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=CASPAR_EXCESS,
        is_margin=True, vix=16, spx_above_200dma=True,
    )
    assert r.recommended_contracts == 1
    assert r.binding_cap == "per_name"
    assert not r.blocked


def test_caspar_blocks_oversized_name():
    # $50 underlying CSP, BPR ~$600 > $466 per-name cap -> 0 contracts, blocked.
    r = size_candidate(
        strategy="CSP", strike=45, underlying=50, premium=1.0,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=CASPAR_EXCESS,
        is_margin=True, vix=16, spx_above_200dma=True,
    )
    assert r.recommended_contracts == 0
    assert r.blocked
    assert "per_name_too_large" in r.breaches


def test_caspar_liquidity_floor_binds_when_excess_low():
    # Excess liquidity barely above the 30% floor -> liquidity floor binds.
    # floor = 0.30 * 9319 = $2796; excess = $2900 -> headroom $104 -> 0 contracts at $250.
    r = size_candidate(
        strategy="CSP", strike=18, underlying=20, premium=0.50,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=2900.0,
        is_margin=True, vix=16, spx_above_200dma=True,
    )
    assert r.recommended_contracts == 0
    assert r.blocked
    assert "liquidity_floor" in r.breaches


def test_caspar_regime_halt_zeroes_aggregate():
    # SPX below 200dma -> aggressive multiplier 0 -> aggregate budget 0 -> blocked.
    r = size_candidate(
        strategy="CSP", strike=18, underlying=20, premium=0.50,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=CASPAR_EXCESS,
        is_margin=True, vix=16, spx_above_200dma=False,
    )
    assert r.blocked
    assert "regime_halt" in r.breaches


def test_caspar_defined_risk_spread_fits():
    # PCS width 5, credit 1.5 -> max loss $350 < $466 per-name -> 1 contract.
    r = size_candidate(
        strategy="PCS", strike=95, underlying=100, premium=1.5, width=5,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=CASPAR_EXCESS,
        is_margin=True, vix=16, spx_above_200dma=True,
    )
    assert r.recommended_contracts == 1
    assert r.bpr_per_contract == 350.0


# ── Sizing: Sarah balanced (cash account) ────────────────────────────────────

SARAH_NLV = 58722.71


def test_sarah_balanced_cash_per_name():
    # Balanced 4% per name = $2,349. Cash-secured CSP on $18 strike = $1,800 -> 1 contract.
    r = size_candidate(
        strategy="CSP", strike=18, underlying=20, premium=0.50,
        profile_name="balanced", nlv=SARAH_NLV, is_margin=False,
        vix=16, spx_above_200dma=True,
    )
    assert r.recommended_contracts == 1
    assert r.binding_cap == "per_name"


def test_group_name_limit_blocks():
    # Two crypto-miner names already open; group_max_names=2 -> blocked.
    r = size_candidate(
        strategy="CSP", strike=18, underlying=20, premium=0.50,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=CASPAR_EXCESS,
        is_margin=True, group_name_count=2, vix=16, spx_above_200dma=True,
    )
    assert r.blocked
    assert "group_name_limit" in r.breaches


def test_aggregate_budget_exhausted():
    # Already deployed near the aggregate ceiling -> aggregate binds.
    agg_ceiling = PROFILES["aggressive"]["aggregate_pct"] * CASPAR_NLV  # $4,660
    r = size_candidate(
        strategy="CSP", strike=18, underlying=20, premium=0.50,
        profile_name="aggressive", nlv=CASPAR_NLV, excess_liquidity=CASPAR_EXCESS,
        is_margin=True, deployed_bpr=agg_ceiling, vix=16, spx_above_200dma=True,
    )
    assert r.recommended_contracts == 0
    assert "aggregate_exhausted" in r.breaches
