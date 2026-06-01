"""Tests for scripts/growth_scan.py — momentum/growth discovery scoring."""
import sys
from pathlib import Path
import importlib.util

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_spec = importlib.util.spec_from_file_location(
    "growth_scan", Path(__file__).resolve().parent.parent / "scripts" / "growth_scan.py")
gs = importlib.util.module_from_spec(_spec)
sys.modules["growth_scan"] = gs
_spec.loader.exec_module(gs)


def test_uptrend_gate():
    assert gs.is_uptrend(110, 105, 100) is True       # price > 50 > 200
    assert gs.is_uptrend(95, 105, 100) is False        # below the 50
    assert gs.is_uptrend(110, 95, 100) is False        # 50 below 200 (not stage 2)
    assert gs.is_uptrend(0, 0, 0) is False


def test_growth_score_rewards_momentum():
    weak = gs.growth_score(buy_score=0, mom_3m_pct=0, rsi=55)
    strong = gs.growth_score(buy_score=60, mom_3m_pct=30, rsi=60)
    assert strong > weak
    assert 0 <= weak <= 100 and 0 <= strong <= 100


def test_growth_score_penalises_blowoff():
    normal = gs.growth_score(buy_score=50, mom_3m_pct=20, rsi=60)
    overbought = gs.growth_score(buy_score=50, mom_3m_pct=20, rsi=85)
    assert overbought < normal


def test_rank_filters_and_sorts():
    cands = [
        {"ticker": "A", "score": 70, "uptrend": True},
        {"ticker": "B", "score": 90, "uptrend": True},
        {"ticker": "C", "score": 95, "uptrend": False},   # not stage-2 → dropped
        {"ticker": "D", "score": 30, "uptrend": True},     # below floor → dropped
    ]
    ranked = gs.rank_candidates(cands)
    assert [c["ticker"] for c in ranked] == ["B", "A"]


def test_confluence_no_signal_is_neutral():
    a = gs.apply_confluence(70.0, None)
    assert a["score"] == 70.0 and a["veto"] is False and a["tag"] == ""


def test_confluence_vetoes_smart_money_selling():
    a = gs.apply_confluence(80.0, {"recommended_strategy": "TRIM"})
    assert a["veto"] is True and "SELLING" in a["tag"]


def test_confluence_boosts_tier_a_with_congress_and_insiders():
    a = gs.apply_confluence(70.0, {
        "tier": "A", "confluence_score": "80", "materiality": "MATERIAL",
        "congress_score": "30", "insider_score": "25", "contract_score": "5"})
    assert a["score"] == 95.0           # 70 + (15 Tier A + 10 cap) × 1.0 MATERIAL
    assert "Tier A" in a["tag"] and "Congress" in a["tag"] and "insiders" in a["tag"]
    assert "gov contracts" not in a["tag"]   # contract_score 5 < 20


def test_confluence_modest_boost_no_tier():
    a = gs.apply_confluence(70.0, {"tier": "", "confluence_score": "40",
                                   "materiality": "MATERIAL"})
    assert a["score"] == 75.0           # 70 + min(10, 40/8=5) × 1.0
    assert a["veto"] is False


def test_confluence_immaterial_signal_is_discounted():
    """A signal too small to move the company gets only a fraction of the boost —
    an immaterial Congress buy on a mega-cap shouldn't drive a momentum buy."""
    base = {"tier": "A", "confluence_score": "80", "congress_score": "30"}
    material = gs.apply_confluence(70.0, {**base, "materiality": "MATERIAL"})
    immaterial = gs.apply_confluence(70.0, {**base, "materiality": "IMMATERIAL"})
    assert immaterial["score"] < material["score"]
    assert immaterial["score"] == 80.0   # 70 + 25 × 0.4
    assert "Immaterial vs co." in immaterial["tag"]


def test_confluence_huge_materiality_amplifies():
    base = {"tier": "A", "confluence_score": "80", "contract_score": "40"}
    material = gs.apply_confluence(60.0, {**base, "materiality": "MATERIAL"})
    huge = gs.apply_confluence(60.0, {**base, "materiality": "HUGE"})
    assert huge["score"] > material["score"]   # 60 + 25×1.25 > 60 + 25×1.0


def test_confluence_blank_materiality_is_conservatively_halved():
    """If materiality couldn't be computed, don't bet hard on the signal."""
    a = gs.apply_confluence(70.0, {"tier": "A", "confluence_score": "80"})
    assert a["score"] == 82.5            # 70 + 25 × 0.5 (unknown materiality)


def test_sizing_note_per_account():
    note = gs.sizing_note({"caspar": 9000, "sarah": 45000})
    assert "Caspar ~$900 (10%)" in note and "Sarah ~$2,250 (5%)" in note


def test_sizing_note_handles_missing_account():
    assert gs.sizing_note({"caspar": 9000}).count("·") == 0   # only one account
    assert gs.sizing_note({}) == ""


def test_screen_candidate_row_constructs():
    from src import schema as S
    row = S.ScreenCandidateRow(
        date="2026-05-30", source="momentum", ticker="NVDA", sector="Tech",
        score=72.0, trigger_price=120.0, stop_price=110.0, rationale="x").to_row()
    assert len(row) == len(S.ScreenCandidateRow.HEADERS)
