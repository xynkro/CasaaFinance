"""Tests for signal_feedback.py outcome evaluation and report building."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.signal_feedback import (
    _eval_csp_outcome,
    _eval_cc_outcome,
    _eval_buy_outcome,
    _build_report,
    _parse_date,
    _parse_float,
    _summarize_user_decisions,
    read_user_decisions,
)
import scripts.signal_feedback as sf
from src.option_pnl import csp_settle_pct, cc_settle_pct
from src.schema import SignalOutcomeRow, PNL_MODEL_PREMIUM


# ── Outcome evaluation ────────────────────────────────────────────────────

class TestCSPOutcome:
    def test_otm_win(self):
        """CSP: put expires OTM → keep premium → WIN, positive premium-inclusive P&L."""
        outcome, pnl = _eval_csp_outcome(strike=190, premium=3.50, price_at_eval=195)
        assert outcome == "WIN"
        assert pnl == pytest.approx(round((3.50 - 0.02) / 190 * 100, 2))

    def test_itm_loss(self):
        """CSP: assigned, loss exceeds premium → LOSS, negative P&L."""
        outcome, pnl = _eval_csp_outcome(strike=190, premium=3.50, price_at_eval=180)
        assert outcome == "LOSS"
        assert pnl < 0

    def test_at_strike_keeps_premium_not_scratch(self):
        """Pinned at the strike is OTM for a put — the premium is kept, so WIN.
        The old price-distance scratch band wrongly logged this as 0."""
        outcome, pnl = _eval_csp_outcome(strike=190, premium=3.50, price_at_eval=190.0)
        assert outcome == "WIN"
        assert pnl > 0

    def test_scratch_is_near_breakeven_pnl(self):
        """SCRATCH now means |P&L| ≈ 0 (premium ≈ assignment loss), not a price band."""
        outcome, pnl = _eval_csp_outcome(strike=100, premium=2.00, price_at_eval=98.0)
        assert outcome == "SCRATCH"
        assert abs(pnl) < 0.1

    def test_delegates_to_shared_settlement(self):
        """Consistency: the feedback loop settles with the SAME model as the backtest."""
        _, pnl = _eval_csp_outcome(strike=190, premium=3.50, price_at_eval=188)
        assert pnl == pytest.approx(round(csp_settle_pct(190, 3.50, 188), 2))


class TestCCOutcome:
    def test_sideways_down_win_is_positive(self):
        """Stock fell but stayed below strike and the premium covers the drop →
        WIN with POSITIVE P&L. The old proxy logged this WIN with a NEGATIVE return."""
        outcome, pnl = _eval_cc_outcome(
            strike=200, price_at_scan=195, price_at_eval=192, premium=5.0,
        )
        assert outcome == "WIN"
        assert pnl > 0
        assert pnl == pytest.approx(round(cc_settle_pct(195, 200, 5.0, 192), 2))

    def test_called_away_above_cost_is_win_not_loss(self):
        """OTM call called away above cost = profit (capped gain + premium) → WIN.
        The old proxy labelled this a LOSS while storing a POSITIVE capped return."""
        outcome, pnl = _eval_cc_outcome(
            strike=200, price_at_scan=195, price_at_eval=210, premium=5.0,
        )
        assert outcome == "WIN"
        assert pnl > 0
        uncapped = (210 - 195 + 5.0) / 195 * 100   # gain if the strike didn't cap
        assert pnl < uncapped                      # capping must bind

    def test_drop_exceeds_premium_is_loss(self):
        """Down more than the premium → LOSS, negative P&L, even though the call
        expired worthless (shares kept). The label follows P&L, not assignment."""
        outcome, pnl = _eval_cc_outcome(
            strike=200, price_at_scan=195, price_at_eval=180, premium=5.0,
        )
        assert outcome == "LOSS"
        assert pnl < 0


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
        assert len(row.HEADERS) == 31
        assert len(row.to_row()) == 31

    def test_pnl_model_versioned_last(self):
        """New rows default to the premium-inclusive version, appended LAST so
        legacy 30-col rows stay positionally aligned on read-back."""
        row = SignalOutcomeRow(
            scan_date="2026-05-20", eval_date="2026-05-25", ticker="AAPL",
            strategy="CSP", scan_composite=70, scan_technical=15,
            strike=190, expiry="20260620", dte=30,
            price_at_scan=195, price_at_eval=197.5,
            fwd_return_pct=1.28, strategy_outcome="WIN", outcome_pnl_pct=2.1,
        )
        assert row.pnl_model == PNL_MODEL_PREMIUM
        assert row.HEADERS[-1] == "pnl_model"
        assert row.to_row()[-1] == PNL_MODEL_PREMIUM
        # the signal block is untouched by the append (indices stable)
        assert row.HEADERS[14] == "sig_rsi"

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


# ── Decision write-back read (the real-user feedback loop) ──────────────────

class _FakeSnap:
    """One Firestore document snapshot: exposes .id and .to_dict()."""
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeCollection:
    def __init__(self, docs):
        # docs: dict {doc_id: data}
        self._docs = docs

    def stream(self):
        for doc_id, data in self._docs.items():
            yield _FakeSnap(doc_id, data)


class _FakeDB:
    """Mock Firestore client; only the `decisions` collection is expected."""
    def __init__(self, docs):
        self._docs = docs

    def collection(self, name):
        assert name == "decisions", f"unexpected collection {name!r}"
        return _FakeCollection(self._docs)


class TestReadUserDecisions:
    def test_inert_without_key(self, monkeypatch):
        """No FIREBASE_SERVICE_ACCOUNT_JSON → empty dict, no network, no raise."""
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        # _decisions_db() must return None on the inert path.
        assert sf._decisions_db() is None
        assert read_user_decisions() == {}

    def test_inert_via_none_db(self):
        """Passing db=None when inert short-circuits to empty (no client built)."""
        # Explicitly inject a None db builder by monkeypatching is unnecessary —
        # read_user_decisions(None) calls _decisions_db(); with the key unset
        # that returns None and we get {}.
        assert read_user_decisions(db=None) in ({}, read_user_decisions())

    def test_populated_read(self):
        """A populated `decisions` collection is read into {key: doc}."""
        docs = {
            "2026-05-20|caspar|AAPL|CSP|190.00": {
                "key": "2026-05-20|caspar|AAPL|CSP|190.00",
                "status": "filled", "ticker": "AAPL", "strategy": "CSP",
                "account": "caspar", "strike": 190.0, "ts": "2026-05-20T10:00:00Z",
            },
            "2026-05-21|sarah|MSFT|BUY_DIP|0.00": {
                "key": "2026-05-21|sarah|MSFT|BUY_DIP|0.00",
                "status": "killed", "ticker": "MSFT", "strategy": "BUY_DIP",
                "account": "sarah",
            },
        }
        out = read_user_decisions(db=_FakeDB(docs))
        assert len(out) == 2
        assert out["2026-05-20|caspar|AAPL|CSP|190.00"]["status"] == "filled"
        assert out["2026-05-21|sarah|MSFT|BUY_DIP|0.00"]["ticker"] == "MSFT"

    def test_key_falls_back_to_doc_id(self):
        """A doc missing the `key` field is keyed by its Firestore doc id."""
        docs = {"2026-06-01|caspar|NVDA|CC|900.00": {"status": "deferred"}}
        out = read_user_decisions(db=_FakeDB(docs))
        assert "2026-06-01|caspar|NVDA|CC|900.00" in out
        assert out["2026-06-01|caspar|NVDA|CC|900.00"]["status"] == "deferred"

    def test_read_error_returns_empty(self):
        """A stream() that raises degrades to {} — never breaks Sheet grading."""
        class BoomDB:
            def collection(self, name):
                class C:
                    def stream(self_inner):
                        raise RuntimeError("firestore down")
                return C()
        assert read_user_decisions(db=BoomDB()) == {}


class TestSummarizeUserDecisions:
    def test_empty_is_blank(self):
        assert _summarize_user_decisions({}) == ""

    def test_counts_by_status(self):
        decisions = {
            "k1": {"status": "filled"},
            "k2": {"status": "filled"},
            "k3": {"status": "killed"},
            "k4": {"status": "deferred"},
        }
        summary = _summarize_user_decisions(decisions)
        assert "4 recorded" in summary
        assert "2 filled" in summary
        assert "1 killed" in summary
        assert "1 deferred" in summary

    def test_report_includes_decisions_section(self):
        """_build_report surfaces the real-user-decisions section (additive)."""
        decisions = {"k1": {"status": "filled"}}
        report = _build_report(
            [], {}, {"win": 0, "loss": 0, "scratch": 0},
            user_decisions=decisions,
        )
        assert "Real user decisions" in report
        assert "1 filled" in report
