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
    assert by["QQQ"]["notional"] == 4500.0 and by["QQQ"]["leg"] == "core"
    assert by["VIXM"]["notional"] == 500.0 and by["VIXM"]["leg"] == "hedge"
    assert by["IEF"]["notional"] == 600.0 and by["IEF"]["leg"] == "protector"
    assert by["GLD"]["notional"] == 400.0 and by["GLD"]["leg"] == "protector"
    assert "TLT" not in by                          # dropped (rate bet, not protection)
    # defensive (hedge + protector) is 15% of NLV; core is 45% on top
    defensive = sum(r["notional"] for r in rows if r["leg"] in ("hedge", "protector"))
    assert round(defensive) == 1500              # 5% + 6% + 4%
    assert round(by["QQQ"]["notional"]) == 4500


def test_plan_always_includes_core_hedge_protector():
    """Even with zero opportunities, the all-rounded sleeves are present."""
    plan = bdp.build_plan(10_000, [], [], TODAY)
    legs = {r["leg"] for r in plan}
    assert {"core", "hedge", "protector"} <= legs
    assert {r["ticker"] for r in plan if r["leg"] == "core"} == {"QQQ"}
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
    # TOP_GROWTH (5) caps growth, TOP_INCOME (2) caps income → all 4 growth + 2 income
    assert sum(1 for r in opps if r["leg"] == "growth") == 4   # AMD included now
    assert sum(1 for r in opps if r["leg"] == "income") == 2
    assert "AMD" in {r["ticker"] for r in opps}                # the name Caspar wanted
    # satellite sized to ~5% NLV each
    assert opps[[r["leg"] for r in opps].index("growth")]["notional"] == 500.0
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


def _screen(n):
    return [{"date": TODAY, "source": "momentum", "ticker": f"T{i}", "score": str(90 - i),
             "rationale": "mom"} for i in range(n)]


def test_macro_lean_hawkish_trims_growth():
    """Hawkish lean → fewer growth names, smaller satellite size (don't add into
    a multiple-compressing tape)."""
    plan = bdp.build_plan(10_000, [], _screen(8), TODAY, lean="hawkish")
    g = [r for r in plan if r["leg"] == "growth"]
    assert len(g) == 3                       # trimmed from 5
    assert g[0]["notional"] == 300.0         # 3% of 10k, not 5%
    assert "macro hawkish" in g[0]["reason"]


def test_macro_lean_dovish_leans_in():
    plan = bdp.build_plan(10_000, [], _screen(8), TODAY, lean="dovish")
    g = [r for r in plan if r["leg"] == "growth"]
    assert len(g) == 5
    assert g[0]["notional"] == 600.0         # leaned in to 6%


def test_macro_lean_neutral_is_baseline():
    plan = bdp.build_plan(10_000, [], _screen(8), TODAY, lean="neutral")
    g = [r for r in plan if r["leg"] == "growth"]
    assert len(g) == 5 and g[0]["notional"] == 500.0   # default 5/5%


def test_macro_lean_schema_roundtrips():
    from src.schema import MacroLeanRow as R
    cells = R(date=TODAY, net_lean="hawkish", summary="CPI→hawkish").to_row()
    assert len(cells) == len(R.HEADERS) and cells[R.HEADERS.index("net_lean")] == "hawkish"


# ── TOP_INCOME quota: wheel + spread families (composite scores are NOT
#    comparable across strategies — ICs saturate ~100, the wheel caps ~62, so
#    a raw top-2-by-composite cut structurally crowded the wheel out) ─────────

def _scan(strategy, ticker, score, **kw):
    base = {"date": TODAY, "ticker": ticker, "strategy": strategy, "strike": "100",
            "premium": "1.50", "dte": "35", "composite_score": str(score), "notes": ""}
    base.update(kw)
    return base


def test_income_quota_wheel_not_crowded_out_by_saturated_ic():
    """The live 2026-06-09 shape: IC 104.1 vs CSP 62 → BOTH must surface."""
    scan = [
        _scan("IC", "IBM", 104.1, notes="SP:90/LP:85/SC:110/LC:115 W:$5"),
        _scan("PCS", "META", 82.0, notes="SP:95/LP:90 W:$5"),
        _scan("CSP", "NVDA", 62.0),
    ]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = [r for r in plan if r["leg"] == "income"]
    strats = {r["strategy"] for r in income}
    assert len(income) == 2
    assert "CSP" in strats, "wheel slot must survive the IC composite saturation"
    assert "IC" in strats, "best spread (by composite within family) takes slot 2"
    assert "PCS" not in strats


def test_income_quota_best_within_each_family():
    scan = [
        _scan("CSP", "NVDA", 62.0),
        _scan("CC", "AMD", 58.0),       # loses the wheel slot to CSP 62
        _scan("IC", "IBM", 104.0),
        _scan("CCS", "TSLA", 99.0),     # loses the spread slot to IC 104
    ]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = {r["strategy"]: r for r in plan if r["leg"] == "income"}
    assert set(income) == {"CSP", "IC"}
    assert income["CSP"]["ticker"] == "NVDA" and income["IC"]["ticker"] == "IBM"


def test_income_quota_spread_only_fills_both_slots():
    scan = [_scan("IC", "IBM", 104.0), _scan("PCS", "META", 82.0)]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = {r["strategy"] for r in plan if r["leg"] == "income"}
    assert income == {"IC", "PCS"}          # no wheel candidates → spreads fill both


def test_income_quota_wheel_only_fills_both_slots():
    scan = [_scan("CSP", "NVDA", 62.0), _scan("CC", "AMD", 55.0)]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = {r["strategy"] for r in plan if r["leg"] == "income"}
    assert income == {"CSP", "CC"}


def test_income_quota_harvest_csp_counts_as_wheel():
    scan = [
        _scan("IC", "IBM", 104.0),
        _scan("HARVEST_CSP", "MARA", 60.0),    # folds to CSP → wheel slot
    ]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = {r["strategy"]: r for r in plan if r["leg"] == "income"}
    assert set(income) == {"CSP", "IC"} and income["CSP"]["ticker"] == "MARA"


def test_income_quota_long_call_backfills_open_slot():
    """LONG_CALL is neither family; it backfills only when a slot stays open."""
    scan = [_scan("CSP", "NVDA", 62.0), _scan("LONG_CALL", "PLTR", 70.0)]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = {r["strategy"] for r in plan if r["leg"] == "income"}
    assert income == {"CSP", "LONG_CALL"}
    # ...but never displaces the two family slots when both exist
    scan += [_scan("IC", "IBM", 104.0)]
    plan = bdp.build_plan(10_000, scan, [], TODAY)
    income = {r["strategy"] for r in plan if r["leg"] == "income"}
    assert income == {"CSP", "IC"}
