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


def test_screen_candidate_row_constructs():
    from src import schema as S
    row = S.ScreenCandidateRow(
        date="2026-05-30", source="momentum", ticker="NVDA", sector="Tech",
        score=72.0, trigger_price=120.0, stop_price=110.0, rationale="x").to_row()
    assert len(row) == len(S.ScreenCandidateRow.HEADERS)
