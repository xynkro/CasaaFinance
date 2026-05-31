"""Tests for scripts/paper_benchmark.py — the SPY-equivalent alpha math."""
import sys
from pathlib import Path
import importlib.util

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_spec = importlib.util.spec_from_file_location(
    "paper_benchmark", Path(__file__).resolve().parent.parent / "scripts" / "paper_benchmark.py")
pb = importlib.util.module_from_spec(_spec)
sys.modules["paper_benchmark"] = pb
_spec.loader.exec_module(pb)


def test_capital_base_equity_is_cost_paid():
    assert pb.capital_base(900.0, None, 7.5) == 900.0
    assert pb.capital_base(-50.0, None, -1) == 50.0   # abs


def test_capital_base_short_option_is_notional_not_credit():
    # CSP: cost_basis is a tiny credit, but the cash-secured capital is strike×100.
    occ = {"underlying": "NVDA", "strike": 100.0, "right": "P", "expiry": "2026-01-16"}
    assert pb.capital_base(-150.0, occ, -1) == 10000.0   # 100 × 100 × 1
    assert pb.capital_base(-300.0, occ, -2) == 20000.0


def test_capital_base_long_option_is_premium_paid():
    occ = {"underlying": "PLTR", "strike": 150.0, "right": "C", "expiry": "2026-01-16"}
    assert pb.capital_base(800.0, occ, 1) == 800.0


def test_spy_equiv_and_alpha():
    # $900 deployed, SPY +5% → SPY would have made $45.
    assert pb.spy_equiv_pl(900.0, 5.0) == 45.0
    beat = pb.position_alpha(position_pl=100.0, capital=900.0, spy_return_pct=5.0)
    assert beat["spy_equiv"] == 45.0 and beat["alpha"] == 55.0 and beat["beat"] is True
    lag = pb.position_alpha(position_pl=10.0, capital=900.0, spy_return_pct=5.0)
    assert lag["alpha"] == -35.0 and lag["beat"] is False


def test_spy_return_uses_close_on_or_before():
    series = {"2026-05-01": 500.0, "2026-05-04": 510.0, "2026-05-29": 550.0}
    # entry on a weekend (05-02) → uses 05-01 close (500); today 05-29 → 550 → +10%
    r = pb.spy_return_since(series, "2026-05-02", "2026-05-29")
    assert abs(r - 10.0) < 1e-9


def test_spy_return_zero_when_no_data():
    assert pb.spy_return_since({}, "2026-05-01", "2026-05-29") == 0.0


def test_benchmark_row_constructs():
    from src import schema as S
    row = S.PaperBenchmarkRow(
        date="2026-05-30", ticker="NVDA", entry_date="2026-05-01", days_held=29,
        cost_basis=900.0, position_pl=100.0, spy_return_pct=5.0, spy_equiv_pl=45.0,
        alpha_pl=55.0, beat_spy=True).to_row()
    assert len(row) == len(S.PaperBenchmarkRow.HEADERS)
