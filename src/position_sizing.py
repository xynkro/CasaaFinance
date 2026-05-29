"""position_sizing.py — risk profiles + position sizing for the options-income book.

Two confirmed profiles (2026-05-29):
  - "aggressive"  → Caspar (small ~$9k IBKR margin account, grow aggressively but
                    survivably; the binding constraint is EXCESS LIQUIDITY, not cash)
  - "balanced"    → Sarah (~S$59k, prioritise not blowing up)

The job of this module: given a candidate (strategy, strike, underlying, premium,
optional spread width) and an account's state (NLV, excess liquidity, margin flag,
already-deployed BPR), answer "how many contracts fit within this profile's caps,
and which cap binds?". Pure functions, no I/O — unit-tested in isolation.

Sizing is expressed in BUYING-POWER REDUCTION (BPR) / capital-at-risk per contract:
  - CSP/CC naked on margin → Reg-T short-option requirement
  - CSP/CC on a cash account → cash-secured notional (strike × 100)
  - PCS/CCS/IC (defined risk) → max loss = (width − credit) × 100  [exact BPR on IBKR]
  - PMCC/LONG_CALL/LONG_PUT → net debit paid (premium × 100)

The caps are SIMULTANEOUS ceilings — the binding (smallest) one wins. The regime
multiplier scales the AGGREGATE budget down; per-name and group caps stay fixed
(you cut contract count, you don't loosen concentration).
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Confirmed profiles ────────────────────────────────────────────────────
# Knobs (all as fraction of NLV unless noted):
#   per_name_pct        — max BPR / capital-at-risk per single name
#   aggregate_pct       — soft aggregate ceiling on total short BPR
#   group_pct           — max per correlated group (e.g. all crypto-miners = 1 group)
#   group_max_names     — max distinct names per correlated group
#   liquidity_floor_pct — (margin) excess liquidity must never drop below this × NLV
#   cash_buffer_pct     — (cash) keep this × NLV free / uncommitted
PROFILES: dict[str, dict] = {
    "aggressive": {
        "label": "Aggressive Growth",
        "per_name_pct": 0.05,
        "aggregate_pct": 0.50,
        "group_pct": 0.10,
        "group_max_names": 2,
        "liquidity_floor_pct": 0.30,
        "cash_buffer_pct": 0.30,
    },
    "balanced": {
        "label": "Balanced",
        "per_name_pct": 0.04,
        "aggregate_pct": 0.30,
        "group_pct": 0.15,
        "group_max_names": 2,
        "liquidity_floor_pct": 0.25,
        "cash_buffer_pct": 0.40,
    },
}

_DEFINED_RISK = {"PCS", "CCS", "IC"}
_DEBIT = {"PMCC", "LONG_CALL", "LONG_PUT"}
_NAKED_SHORT = {"CSP", "CC", "HARVEST_CSP"}


def regime_multiplier(vix: float, spx_above_200dma: bool, profile_name: str) -> float:
    """Scale the AGGREGATE budget down in adverse regimes.

    aggressive: SPX<200dma or VIX>30 → 0.0 (no new shorts — matches the macro HALT);
                VIX 25-30 → 0.5; else 1.0.
    balanced:   SPX<200dma AND VIX>30 → 0.33; SPX<200dma or VIX>30 → 0.5;
                VIX>25 → 0.66; else 1.0.
    """
    vix = vix or 0.0
    weak_trend = not spx_above_200dma
    if profile_name == "aggressive":
        if weak_trend or vix > 30:
            return 0.0
        if vix > 25:
            return 0.5
        return 1.0
    # balanced
    if weak_trend and vix > 30:
        return 0.33
    if weak_trend or vix > 30:
        return 0.5
    if vix > 25:
        return 0.66
    return 1.0


def estimate_bpr_per_contract(
    strategy: str,
    strike: float,
    underlying: float,
    premium: float,
    width: float | None = None,
    is_margin: bool = True,
) -> float:
    """Per-contract buying-power reduction / capital at risk, in account currency.

    premium is the per-share credit (CSP/CC/spreads) or per-share debit (PMCC/longs).
    width is the spread width in points (required for PCS/CCS/IC to be exact).
    """
    strat = (strategy or "").upper()
    premium = abs(premium or 0.0)

    if strat in _DEFINED_RISK and width and width > 0:
        # Max loss on a vertical/condor = (width − net credit) × 100. This IS the
        # IBKR BPR for a defined-risk spread.
        return max(0.0, width - premium) * 100.0

    if strat in _DEBIT:
        # Debit paid is the entire capital at risk.
        return premium * 100.0

    # Naked short put/call (CSP/CC).
    if strike <= 0:
        return 0.0
    if not is_margin:
        # Cash-secured: full notional (CC collateral is the shares; treat as strike×100
        # as a conservative cash-account proxy).
        return strike * 100.0
    # Reg-T short-option requirement:
    #   max( 0.20×underlying − OTM_amount,  0.10×strike ) × 100  +  premium×100
    if strat == "CC":
        otm_amount = max(0.0, strike - underlying)   # call strike above spot
    else:  # CSP / HARVEST_CSP
        otm_amount = max(0.0, underlying - strike)   # put strike below spot
    req_a = (0.20 * underlying - otm_amount + premium) * 100.0
    req_b = (0.10 * strike + premium) * 100.0
    return max(req_a, req_b, premium * 100.0)


@dataclass
class SizingResult:
    bpr_per_contract: float
    recommended_contracts: int
    blocked: bool
    regime_mult: float
    binding_cap: str          # which cap determined the count
    breaches: list[str]
    caps: dict                # contracts allowed by each cap (None = not applicable)

    def to_note(self) -> str:
        if self.blocked:
            return f"SIZE: 0 contracts — {', '.join(self.breaches) or 'capped'}"
        return (f"SIZE: {self.recommended_contracts}x "
                f"(${self.bpr_per_contract:.0f} BPR/ct, bind={self.binding_cap})")


def size_candidate(
    *,
    strategy: str,
    strike: float,
    underlying: float,
    premium: float,
    profile_name: str,
    nlv: float,
    excess_liquidity: float | None = None,
    is_margin: bool = True,
    width: float | None = None,
    deployed_bpr: float = 0.0,
    group_deployed_bpr: float = 0.0,
    group_name_count: int = 0,
    vix: float = 0.0,
    spx_above_200dma: bool = True,
) -> SizingResult:
    """Recommend a contract count for one candidate under a profile + account state.

    deployed_bpr        — short BPR already committed across the whole book
    group_deployed_bpr  — short BPR already committed in this name's correlated group
    group_name_count     — distinct names already open in this correlated group
    """
    p = PROFILES.get(profile_name, PROFILES["balanced"])
    bpr = estimate_bpr_per_contract(strategy, strike, underlying, premium, width, is_margin)
    mult = regime_multiplier(vix, spx_above_200dma, profile_name)

    if nlv <= 0 or bpr <= 0:
        return SizingResult(bpr, 0, True, mult, "none",
                            ["no_nlv_or_bpr"], {})

    BIG = 10 ** 9
    # per-name cap
    max_by_name = int((p["per_name_pct"] * nlv) // bpr)
    # aggregate cap (regime-scaled)
    agg_budget = p["aggregate_pct"] * nlv * mult
    max_by_agg = int(max(0.0, agg_budget - deployed_bpr) // bpr)
    # correlated-group cap (dollar)
    group_budget = p["group_pct"] * nlv
    max_by_group = int(max(0.0, group_budget - group_deployed_bpr) // bpr)
    # correlated-group cap (name count)
    group_name_full = group_name_count >= p["group_max_names"]
    # liquidity floor (margin accounts) / cash buffer (cash accounts)
    if is_margin and excess_liquidity is not None:
        liq_headroom = max(0.0, excess_liquidity - p["liquidity_floor_pct"] * nlv)
        max_by_liq = int(liq_headroom // bpr)
        liq_label = "liquidity_floor"
    elif not is_margin:
        # cash account: aggregate already enforces deployment; buffer is the
        # complement of aggregate, so no separate binding term here.
        max_by_liq = BIG
        liq_label = "cash_buffer"
    else:
        max_by_liq = BIG
        liq_label = "liquidity_floor"

    candidates = {
        "per_name": max_by_name,
        "aggregate": max_by_agg,
        "group_$": max_by_group,
        liq_label: max_by_liq,
    }
    if group_name_full:
        candidates["group_names"] = 0

    rec = max(0, min(candidates.values()))
    binding = min(candidates, key=lambda k: candidates[k])

    breaches: list[str] = []
    if rec == 0:
        if max_by_name == 0:
            breaches.append("per_name_too_large")
        if max_by_agg == 0:
            breaches.append("aggregate_exhausted")
        if max_by_group == 0:
            breaches.append("group_budget_exhausted")
        if group_name_full:
            breaches.append("group_name_limit")
        if is_margin and excess_liquidity is not None and max_by_liq == 0:
            breaches.append("liquidity_floor")
        if mult == 0.0:
            breaches.append("regime_halt")

    caps_display = {k: (None if v >= BIG else v) for k, v in candidates.items()}
    return SizingResult(
        bpr_per_contract=round(bpr, 2),
        recommended_contracts=rec,
        blocked=rec == 0,
        regime_mult=mult,
        binding_cap=binding,
        breaches=breaches,
        caps=caps_display,
    )
