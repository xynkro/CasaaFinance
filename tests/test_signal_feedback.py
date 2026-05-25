"""Tests for signal_feedback.py outcome evaluation and report building."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.signal_feedback import (
    _eval_csp_outcome,
    _eval_cc_outcome,
    _eval_buy_outcome,
    _build_report,
    _parse_date,
    _parse_float,
)
from src.schema import SignalOutcomeRow


# ── Outcome evaluation ────────────────────────────────────────────────────

class TestCSPOutcome:
    def test_otm_win(self):
        """CSP: price above strike at expiry → WIN."""
        outcome, pnl = _eval_csp_outcome(
            strike=190, premium=3.50, price_at_eval=195, cash_required=19000,
        )
        assert outcome == "WIN"
        assert pnl > 0

    def test_itm_loss(self):
        """CSP: price below strike at expiry → LOSS."""
        outcome, pnl = _eval_csp_outcome(
            strike=190, premium=3.50, price_at_eval=180, cash_required=19000,
        )
        assert outcome == "LOSS"
        assert pnl < 0

    def test_scratch(self):
        """CSP: price very close to strike → SCRATCH."""
        outcome, _ = _eval_csp_outcome(
            strike=190, premium=3.50, price_at_eval=190.0, cash_required=19000,
        )
        assert outcome == "SCRATCH"

    def test_zero_cash_required_fallback(self):
        """CSP: cash_required=0 should use strike*100 fallback."""
        outcome, pnl = _eval_csp_outcome(
            strike=100, premium=2.0, price_at_eval=105, cash_required=0,
        )
        assert outcome == "WIN"
        assert pnl > 0


class TestCCOutcome:
    def test_otm_win(self):
        """CC: price below strike at expiry → WIN (keep premium + stock)."""
        outcome, _ = _eval_cc_outcome(strike=200, price_at_scan=195, price_at_eval=192)
        assert outcome == "WIN"

    def test_itm_loss(self):
        """CC: price above strike → LOSS (called away)."""
        outcome, pnl = _eval_cc_outcome(strike=200, price_at_scan=195, price_at_eval=210)
        assert outcome == "LOSS"
        # P&L should be capped at strike / scan_price - 1
        assert pnl < 10  # < the full 7.7% move


class TestBuyOutcome:
    def test_up_win(self):
        outcome, pnl = _eval_buy_outcome(100, 108)
        assert outcome == "WIN"
        assert abs(pnl - 8.0) < 0.1

    def test_down_loss(self):
        outcome, pnl = _eval_buy_outcome(100, 95)
        assert outcome == "LOSS"
        assert pnl < 0

    def test_flat_scratch(self):
        outcome, _ = _eval_buy_outcome(100, 100.3)
        assert outcome == "SCRATCH"

    def test_zero_price_guard(self):
        outcome, _ = _eval_buy_outcome(0, 100)
        assert outcome == "SCRATCH"


# ── Helpers ────────────────────────────────────────────────────────────────

class TestParsers:
    def test_parse_date_iso(self):
        dt = _parse_date("2026-05-20")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 5 and dt.day == 20

    def test_parse_date_with_audit_suffix(self):
        dt = _parse_date("2026-05-20T143022")
        assert dt is not None
        assert dt.day == 20

    def test_parse_date_empty(self):
        assert _parse_date("") is None
        assert _parse_date(None) is None

    def test_parse_float_normal(self):
        assert _parse_float("3.14") == 3.14
        assert _parse_float("0") == 0.0

    def test_parse_float_invalid(self):
        assert _parse_float("", 99) == 99
        assert _parse_float("N/A") == 0.0


# ── Schema ─────────────────────────────────────────────────────────────────

class TestSignalOutcomeRow:
    def test_construction(self):
        row = SignalOutcomeRow(
            scan_date="2026-05-20", eval_date="2026-05-25", ticker="AAPL",
            strategy="CSP", scan_composite=72.5, scan_technical=15.3,
            strike=190, expiry="20260620", dte=30,
            price_at_scan=195, price_at_eval=197.5,
            fwd_return_pct=1.28, strategy_outcome="WIN", outcome_pnl_pct=2.1,
        )
        assert row.TAB_NAME == "signal_outcomes"
        assert len(row.HEADERS) == 30
        assert len(row.to_row()) == 30

    def test_signal_values_stored(self):
        row = SignalOutcomeRow(
            scan_date="2026-05-20", eval_date="2026-05-25", ticker="AAPL",
            strategy="CSP", scan_composite=50, scan_technical=10,
            strike=190, expiry="20260620", dte=30,
            price_at_scan=195, price_at_eval=200,
            fwd_return_pct=2.56, strategy_outcome="WIN", outcome_pnl_pct=1.5,
            sig_rsi=-0.35, sig_fib_support=0.8, sig_iv_rv_ratio=0.6,
        )
        data = row.to_row()
        # sig_rsi is at index 14 (after the 14 header fields)
        assert data[14] == "-0.350"  # sig_rsi
        assert data[25] == "0.800"   # sig_fib_support
        assert data[28] == "0.600"   # sig_iv_rv_ratio


# ── Report building ───────────────────────────────────────────────────────

class TestBuildReport:
    def _make_outcomes(self, n_win=3, n_loss=1):
        outcomes = []
        for i in range(n_win):
            outcomes.append(SignalOutcomeRow(
                scan_date="2026-05-01", eval_date="2026-06-01", ticker=f"T{i}",
                strategy="CSP", scan_composite=70, scan_technical=15,
                strike=100, expiry="20260601", dte=30,
                price_at_scan=105, price_at_eval=108,
                fwd_return_pct=2.86, strategy_outcome="WIN", outcome_pnl_pct=1.5,
            ))
        for i in range(n_loss):
            outcomes.append(SignalOutcomeRow(
                scan_date="2026-05-01", eval_date="2026-06-01", ticker=f"L{i}",
                strategy="CSP", scan_composite=50, scan_technical=5,
                strike=100, expiry="20260601", dte=30,
                price_at_scan=105, price_at_eval=95,
                fwd_return_pct=-9.52, strategy_outcome="LOSS", outcome_pnl_pct=-3.0,
            ))
        return outcomes

    def test_basic_report(self):
        outcomes = self._make_outcomes(3, 1)
        stats = {"win": 3, "loss": 1, "scratch": 0}
        report = _build_report(outcomes, {}, stats)
        assert "75%" in report  # 3/4 = 75%
        assert "CSP" in report
        assert "Signal Feedback Report" in report

    def test_small_sample_warning(self):
        outcomes = self._make_outcomes(2, 1)
        stats = {"win": 2, "loss": 1, "scratch": 0}
        report = _build_report(outcomes, {}, stats)
        assert "Small sample" in report

    def test_empty_report(self):
        report = _build_report([], {}, {"win": 0, "loss": 0, "scratch": 0})
        assert "No outcomes" in report
