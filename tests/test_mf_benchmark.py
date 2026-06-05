# tests/test_mf_benchmark.py — MF sleeve isolation vs SPY (Task 8)
from scripts.paper_benchmark import mf_sleeve_alpha
from src.schema import PaperBenchmarkRow as R


def _row(tk, pl, equiv):
    return R(date="2026-06-06", ticker=tk, entry_date="2026-06-01", days_held=5,
             cost_basis=100.0, position_pl=pl, spy_return_pct=1.0,
             spy_equiv_pl=equiv, alpha_pl=pl - equiv, beat_spy=pl > equiv)


def test_mf_sleeve_filters_and_sums():
    rows = [_row("AMZN", 100.0, 60.0), _row("NVDA", 50.0, 40.0), _row("TOTAL", 150.0, 100.0)]
    mf = mf_sleeve_alpha(rows, {"AMZN"})            # only AMZN is MF-sourced
    assert mf["position_pl"] == 100.0 and mf["spy_equiv_pl"] == 60.0
    assert mf["alpha_pl"] == 40.0 and mf["beat_spy"] is True and mf["n"] == 1


def test_mf_sleeve_none_when_no_mf_held():
    rows = [_row("NVDA", 50.0, 40.0), _row("TOTAL", 50.0, 40.0)]
    assert mf_sleeve_alpha(rows, {"AMZN"}) is None  # nothing to isolate


def test_mf_sleeve_aggregates_multiple_and_ignores_total():
    rows = [_row("AMZN", 100.0, 60.0), _row("INTC", -20.0, 10.0), _row("TOTAL", 80.0, 70.0)]
    mf = mf_sleeve_alpha(rows, {"AMZN", "INTC"})
    assert mf["n"] == 2
    assert mf["position_pl"] == 80.0 and mf["spy_equiv_pl"] == 70.0
    assert mf["alpha_pl"] == 10.0 and mf["beat_spy"] is True
