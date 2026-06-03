"""Tests for the unified daily-plan builder (standing allocation + opportunities)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "build_daily_plan", ROOT / "scripts" / "build_daily_plan.py")
bdp = importlib.util.module_from_spec(_spec)
sys.modules["build_daily_plan"] = bdp
_spec.loader.exec_module(bdp)

TODAY = "2026-06-01"


def test_standing_allocation_sizes_to_nlv():
    rows = bdp.standing_allocation_rows(10_000)
    by = {r["ticker"]: r for r in rows}
    assert by["VIXM"]["notional"] == 500.0 and by["VIXM"]["leg"] == "hedge"
    assert by["IEF"]["notional"] == 700.0 and by["IEF"]["leg"] == "protector"
    assert by["TLT"]["notional"] == 600.0
    assert by["GLD"]["notional"] == 500.0
    # hedge + protector together ≈ 23% of NLV
    assert round(sum(r["notional"] for r in rows)) == 2300


def test_plan_always_includes_hedge_and_protector():
    """Even with zero opportunities, the all-rounded sleeves are present."""
    plan = bdp.build_plan(10_000, [], [], TODAY)
    legs = {r["leg"] for r in plan}
    assert "hedge" in legs and "protector" in legs
    assert {r["ticker"] for r in plan if r["leg"] == "hedge"} == {"VIXM"}


def test_opportunities_are_a_mix_capped_and_ranked():
    scan = [
        {"date": TODAY, "ticker": "META", "strategy": "PCS", "strike": "585",
         "premium": "2.30", "dte": "39", "composite_score": "70", "notes": "x"},
        {"date": TODAY, "ticker": "IBM", "strategy": "IC", "strike": "290",
         "premium": "3.68", "dte": "46", "composite_score": "55", "notes": "y"},
    ]
    screen = [
        {"date": TODAY, "source": "momentum", "ticker": "NBIS", "score": "85", "rationale": "mom"},
        {"date": TODAY, "source": "momentum", "ticker": "AMD", "score": "81", "rationale": "mom"},
        {"date": TODAY, "source": "momentum", "ticker": "QCOM", "score": "80", "rationale": "mom"},
        {"date": TODAY, "source": "momentum", "ticker": "AVGO", "score": "79", "rationale": "mom"},
    ]
    plan = bdp.build_plan(10_000, scan, screen, TODAY)
    opps = [r for r in plan if r["leg"] in ("growth", "income")]
    # TOP_GROWTH (3) + TOP_INCOME (2) = 5 opportunities max
    assert len(opps) == 5
    assert sum(1 for r in opps if r["leg"] == "growth") == 3   # NBIS/AMD/QCOM (top 3)
    assert sum(1 for r in opps if r["leg"] == "income") == 2   # META/IBM
    assert "AVGO" not in {r["ticker"] for r in opps}           # 4th growth dropped
    # opportunities ranked by conviction desc
    convs = [r["conviction"] for r in opps]
    assert convs == sorted(convs, reverse=True)


def test_everything_in_plan_is_flagged_execute_with_ranks():
    plan = bdp.build_plan(10_000, [], [], TODAY)
    assert all(r["execute"] for r in plan)
    assert [r["rank"] for r in plan] == list(range(1, len(plan) + 1))


def test_income_picks_best_per_strategy_only():
    """Two PCS candidates → only the higher-conviction one reaches the plan."""
    scan = [
        {"date": TODAY, "ticker": "META", "strategy": "PCS", "strike": "585",
         "premium": "2.30", "dte": "39", "composite_score": "70", "notes": ""},
        {"date": TODAY, "ticker": "NVDA", "strategy": "PCS", "strike": "120",
         "premium": "1.10", "dte": "39", "composite_score": "40", "notes": ""},
    ]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = [r for r in plan if r["leg"] == "income"]
    assert len(income) == 1 and income[0]["ticker"] == "META"


def test_schema_row_roundtrips():
    from src.schema import DailyPlanRow as R
    row = R(date=TODAY, rank=1, leg="hedge", ticker="VIXM", strategy="ALLOC",
            detail="5% NLV → $400", conviction=100, target_pct=5.0,
            notional=400.0, reason="hedge", source="risk_parity", execute=True)
    cells = row.to_row()
    assert len(cells) == len(R.HEADERS)
    idx = {h: i for i, h in enumerate(R.HEADERS)}
    assert cells[idx["execute"]] == "TRUE"
    assert cells[idx["ticker"]] == "VIXM"
    assert cells[idx["leg"]] == "hedge"
