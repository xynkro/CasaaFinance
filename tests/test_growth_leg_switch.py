"""GROWTH leg switch — the momentum satellite is OFF by default (2026-10-09).

paper_benchmark put the momentum book at -$2,701 alpha vs SPY-equivalent on
2026-09-26 and -$1,458 on 2026-10-09; its ranking is the same family as the
anti-predictive composite_score. The switch is a flat strategy default like
SPREADS_ENABLED, NOT a regime gate — the executor still mirrors ungated intent.

Two layers are pinned: the plan BUILDER stops emitting growth rows, and the
EXECUTOR refuses to place them, so a stale plan row can't buy a momentum name.
"""
import importlib

import pytest

import scripts.alpaca_paper_execute as ex
import scripts.build_daily_plan as bdp

TODAY = "2026-10-09"


def _screen():
    return [{"date": TODAY, "source": "momentum", "ticker": t, "score": s,
             "trigger_price": "100", "rationale": "Momentum: 3mo +"}
            for t, s in (("PLTR", "85.8"), ("ZS", "83"), ("U", "81.5"))]


def _curated():
    return [{"date": TODAY, "role": "core", "ticker": "COST"}]


def _plan(**kw):
    return bdp.build_plan(nlv=10_000.0, scan_rows=[], screen_rows=_screen(),
                          today=TODAY, curated_rows=_curated(), **kw)


# ── default ──────────────────────────────────────────────────────────────────

def test_default_is_off_when_env_unset(monkeypatch):
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    importlib.reload(bdp)
    importlib.reload(ex)
    assert bdp.GROWTH_LEG_ENABLED is False
    assert ex.GROWTH_LEG_ENABLED is False


def test_env_true_re_enables(monkeypatch):
    monkeypatch.setenv("GROWTH_LEG_ENABLED", "true")
    importlib.reload(bdp)
    importlib.reload(ex)
    assert bdp.GROWTH_LEG_ENABLED is True
    assert ex.GROWTH_LEG_ENABLED is True
    monkeypatch.delenv("GROWTH_LEG_ENABLED")
    importlib.reload(bdp)
    importlib.reload(ex)


# ── builder ──────────────────────────────────────────────────────────────────

def test_no_growth_rows_when_disabled():
    plan = _plan(growth_enabled=False)
    assert [r for r in plan if r["leg"] == "growth"] == []


def test_growth_rows_present_when_enabled():
    plan = _plan(growth_enabled=True)
    assert {r["ticker"] for r in plan if r["leg"] == "growth"} == {"PLTR", "ZS", "U"}


def test_standing_allocation_unaffected():
    plan = _plan(growth_enabled=False)
    legs = {r["leg"] for r in plan}
    assert {"core", "hedge", "protector"} <= legs


def test_mf_core_sleeve_unaffected():
    """Motley Fool core is a different sleeve — the switch must not touch it."""
    plan = _plan(growth_enabled=False)
    assert [r["ticker"] for r in plan if r["leg"] == "mf_core"] == ["COST"]


def test_ranks_still_contiguous_without_growth():
    plan = _plan(growth_enabled=False)
    assert [r["rank"] for r in plan] == list(range(1, len(plan) + 1))


# ── executor ─────────────────────────────────────────────────────────────────

def test_executor_skip_reason_when_disabled():
    reason = ex.growth_leg_skip_reason(enabled=False)
    assert reason and reason.startswith("skipped:")
    assert "GROWTH_LEG_ENABLED" in reason


def test_executor_proceeds_when_enabled():
    assert ex.growth_leg_skip_reason(enabled=True) is None
