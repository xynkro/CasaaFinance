"""Tests for gov/insider materiality — investment size vs company size."""
from __future__ import annotations

import pytest


def test_huge_contract_vs_small_company():
    """$50M contract on a $100M-revenue company → 50% of rev → HUGE."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=50e6, insider_usd=0,
                            ttm_revenue=100e6, market_cap=300e6)
    assert m["materiality"] == "HUGE"
    assert m["contract_pct_rev"] == 0.5
    assert m["contract_pct_mktcap"] == round(50e6 / 300e6, 4)  # stored to 4 dp


def test_immaterial_contract_vs_mega_cap():
    """$50M contract on a $300B mega-cap (≈$200B rev) → rounding error."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=50e6, insider_usd=0,
                            ttm_revenue=200e9, market_cap=300e9)
    assert m["materiality"] == "IMMATERIAL"
    assert m["contract_pct_rev"] < 0.001


def test_material_and_notable_bands():
    from scripts.screen_gov_confluence import compute_materiality
    # 8% of revenue → MATERIAL
    assert compute_materiality(8e6, 0, 100e6, 1e9)["materiality"] == "MATERIAL"
    # 2% of revenue → NOTABLE
    assert compute_materiality(2e6, 0, 100e6, 1e9)["materiality"] == "NOTABLE"


def test_falls_back_to_market_cap_when_no_revenue():
    """Pre-revenue company (rev unknown) → label driven by market-cap impact."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=30e6, insider_usd=0,
                            ttm_revenue=None, market_cap=100e6)
    # 30% of market cap → HUGE via fallback
    assert m["materiality"] == "HUGE"
    assert m["contract_pct_rev"] == 0.0
    assert m["contract_pct_mktcap"] == 0.3


def test_insider_cluster_vs_small_cap_is_material():
    """Insider-only signal: $5M of buys = 1% of a $500M-cap company → a real
    equity flow → HUGE (flows are sized vs market cap, not revenue)."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=0, insider_usd=5e6,
                            ttm_revenue=100e6, market_cap=500e6)
    assert m["materiality"] == "HUGE"            # 1% of cap → top flow band
    assert m["insider_pct_mktcap"] == round(5e6 / 500e6, 4)


def test_congress_buy_on_megacap_is_immaterial():
    """A $50k Congress buy on a $4.6T company is a rounding error → IMMATERIAL.
    This is the 'will it move the stock?' answer the user wants: no."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=0, insider_usd=0, ttm_revenue=451e9,
                            market_cap=4.6e12, congress_usd=50_000)
    assert m["materiality"] == "IMMATERIAL"
    assert m["congress_pct_mktcap"] == 0.0       # 50k/4.6T rounds to 0.0000
    assert m["market_cap"] == 4.6e12             # company size echoed back
    assert m["ttm_revenue"] == 451e9


def test_company_size_echoed_for_pwa():
    """The PWA needs the raw company size to render 'Company: $Xcap / $Yrev'."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=10e6, insider_usd=0,
                            ttm_revenue=2e9, market_cap=6e9)
    assert m["market_cap"] == 6e9
    assert m["ttm_revenue"] == 2e9


def test_contract_present_but_no_denominator():
    """Contract exists but neither revenue nor cap known → no false label."""
    from scripts.screen_gov_confluence import compute_materiality
    m = compute_materiality(contract_usd=10e6, insider_usd=0,
                            ttm_revenue=None, market_cap=None)
    assert m["materiality"] == ""
    assert m["contract_pct_rev"] == 0.0
    assert m["contract_pct_mktcap"] == 0.0


def test_schema_row_roundtrips_new_fields():
    """GovConfluenceSignalRow.to_row must include the 6 materiality columns
    in HEADERS order."""
    from src.schema import GovConfluenceSignalRow as R
    row = R(date="2026-06-01", ticker="TEST", confluence_score=72,
            contract_score=80, congress_score=40, insider_score=30,
            contract_usd=50e6, contract_pct_rev=0.34,
            contract_pct_mktcap=0.012, insider_usd=2e6,
            insider_pct_mktcap=0.001, materiality="MATERIAL",
            market_cap=6e9, ttm_revenue=2e9, congress_usd=120_000,
            congress_pct_mktcap=0.0)
    cells = row.to_row()
    assert len(cells) == len(R.HEADERS)
    idx = {h: i for i, h in enumerate(R.HEADERS)}
    assert cells[idx["materiality"]] == "MATERIAL"
    assert float(cells[idx["contract_pct_rev"]]) == 0.34
    assert float(cells[idx["market_cap"]]) == 6e9
    assert float(cells[idx["ttm_revenue"]]) == 2e9
    assert float(cells[idx["congress_usd"]]) == 120_000
