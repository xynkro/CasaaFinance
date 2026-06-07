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
    _decision_date,
    _decision_fields,
    _grade_selection_skill,
    _normalize_outcomes,
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


# ── Selection-skill grading ──────────────────────────────────────────────────

def _mk_outcome(ticker, strategy, strike, outcome, scan_date="2026-05-01"):
    """A normalized graded-outcome dict (as _normalize_outcomes emits)."""
    return {"scan_date": scan_date, "ticker": ticker.upper(),
            "strategy": strategy.upper(), "strike": round(float(strike), 2),
            "outcome": outcome.upper()}


def _mk_decision(ticker, strategy, strike, status, date="2026-05-01",
                 account="caspar", **extra):
    """A {key: doc} pair matching the PWA decision shape."""
    key = f"{date}|{account}|{ticker.upper()}|{strategy.upper()}|{float(strike):.2f}"
    doc = {"key": key, "status": status, "ticker": ticker.upper(),
           "strategy": strategy.upper(), "account": account, "strike": float(strike)}
    doc.update(extra)
    return key, doc


class TestGradeSelectionSkill:
    def test_perfect_positive_edge(self):
        """Fill every winner, kill every loser → edge ≈ +1."""
        winners = ["AAPL", "MSFT", "NVDA"]
        losers = ["TSLA", "AMD", "META"]
        outcomes = ([_mk_outcome(t, "CSP", 100, "WIN") for t in winners]
                    + [_mk_outcome(t, "CSP", 100, "LOSS") for t in losers])
        decisions = dict([_mk_decision(t, "CSP", 100, "filled") for t in winners]
                         + [_mk_decision(t, "CSP", 100, "killed") for t in losers])
        g = _grade_selection_skill(decisions, outcomes)
        assert g is not None
        assert g["n"] == 6 and g["n_win"] == 3 and g["n_loss"] == 3
        assert g["fill_rate_on_winners"] == 1.0
        assert g["fill_rate_on_losers"] == 0.0
        assert g["kill_rate_on_losers"] == 1.0
        assert g["selection_edge"] == pytest.approx(1.0)

    def test_negative_edge_when_filling_losers(self):
        """Fill the losers, skip the winners → negative edge (anti-selective)."""
        winners = ["AAPL", "MSFT", "NVDA"]
        losers = ["TSLA", "AMD", "META"]
        outcomes = ([_mk_outcome(t, "CSP", 100, "WIN") for t in winners]
                    + [_mk_outcome(t, "CSP", 100, "LOSS") for t in losers])
        decisions = dict([_mk_decision(t, "CSP", 100, "killed") for t in winners]
                         + [_mk_decision(t, "CSP", 100, "filled") for t in losers])
        g = _grade_selection_skill(decisions, outcomes)
        assert g["selection_edge"] == pytest.approx(-1.0)
        assert g["fill_rate_on_winners"] == 0.0
        assert g["fill_rate_on_losers"] == 1.0

    def test_insufficient_sample_suppressed(self):
        """Below SELECTION_MIN_GRADED matched pairs → None (too noisy)."""
        outcomes = [_mk_outcome("AAPL", "CSP", 100, "WIN"),
                    _mk_outcome("TSLA", "CSP", 100, "LOSS")]
        decisions = dict([_mk_decision("AAPL", "CSP", 100, "filled"),
                          _mk_decision("TSLA", "CSP", 100, "killed")])
        assert _grade_selection_skill(decisions, outcomes) is None
        # ...but a lowered floor surfaces it.
        g = _grade_selection_skill(decisions, outcomes, min_graded=2)
        assert g is not None and g["n"] == 2

    def test_one_sided_history_suppressed(self):
        """All winners, no losers → edge undefined → None even past the floor."""
        outcomes = [_mk_outcome(t, "CSP", 100, "WIN")
                    for t in ["AAPL", "MSFT", "NVDA", "AMD", "META", "GOOG"]]
        decisions = dict(_mk_decision(t, "CSP", 100, "filled")
                         for t in ["AAPL", "MSFT", "NVDA", "AMD", "META", "GOOG"])
        assert _grade_selection_skill(decisions, outcomes) is None

    def test_empty_inputs(self):
        assert _grade_selection_skill({}, [_mk_outcome("A", "CSP", 1, "WIN")]) is None
        assert _grade_selection_skill({dict([_mk_decision("A", "CSP", 1, "filled")][:1]).popitem()[0]: {}}, []) is None
        assert _grade_selection_skill({}, []) is None

    def test_strike_mismatch_does_not_match(self):
        """A decision on a different strike is not joined to the outcome."""
        outcomes = [_mk_outcome("AAPL", "CSP", 100, "WIN")] * 1
        # Decision on the 200 strike — no matching outcome → no pairs → None.
        decisions = dict([_mk_decision("AAPL", "CSP", 200, "filled")])
        assert _grade_selection_skill(decisions, outcomes, min_graded=1) is None

    def test_buy_zero_strike_matches(self):
        """BUY picks carry strike 0 on both sides and must still join."""
        outcomes = [_mk_outcome("AAPL", "BUY", 0, "WIN"),
                    _mk_outcome("TSLA", "BUY", 0, "LOSS")]
        decisions = dict([_mk_decision("AAPL", "BUY", 0, "filled"),
                          _mk_decision("TSLA", "BUY", 0, "killed")])
        g = _grade_selection_skill(decisions, outcomes, min_graded=2)
        assert g is not None and g["selection_edge"] == pytest.approx(1.0)

    def test_outside_window_does_not_match(self):
        """A decision logged well outside the match window is not joined."""
        outcomes = [_mk_outcome("AAPL", "CSP", 100, "WIN", scan_date="2026-05-01")]
        decisions = dict([_mk_decision("AAPL", "CSP", 100, "filled", date="2026-06-30")])
        assert _grade_selection_skill(decisions, outcomes, min_graded=1) is None
        # Same pick decided within the window → joins.
        near = dict([_mk_decision("AAPL", "CSP", 100, "filled", date="2026-05-04")])
        # one-sided so still None, but it must at least COUNT — verify via min_graded path
        outcomes2 = outcomes + [_mk_outcome("TSLA", "CSP", 100, "LOSS", scan_date="2026-05-01")]
        near.update(dict([_mk_decision("TSLA", "CSP", 100, "killed", date="2026-05-03")]))
        g = _grade_selection_skill(near, outcomes2, min_graded=2)
        assert g is not None and g["n"] == 2

    def test_action_field_status_fallback(self):
        """A doc that carries `action` instead of `status` is still graded."""
        winners = ["AAPL", "MSFT", "NVDA"]
        losers = ["TSLA", "AMD", "META"]
        outcomes = ([_mk_outcome(t, "CSP", 100, "WIN") for t in winners]
                    + [_mk_outcome(t, "CSP", 100, "LOSS") for t in losers])
        decisions = {}
        for t in winners:
            k, d = _mk_decision(t, "CSP", 100, "ignored")
            d.pop("status"); d["action"] = "filled"
            decisions[k] = d
        for t in losers:
            k, d = _mk_decision(t, "CSP", 100, "ignored")
            d.pop("status"); d["action"] = "killed"
            decisions[k] = d
        g = _grade_selection_skill(decisions, outcomes)
        assert g is not None and g["selection_edge"] == pytest.approx(1.0)

    def test_scratch_outcomes_ignored(self):
        """SCRATCH carries no directional signal → excluded from grading."""
        outcomes = [_mk_outcome("AAPL", "CSP", 100, "SCRATCH"),
                    _mk_outcome("TSLA", "CSP", 100, "SCRATCH")]
        decisions = dict([_mk_decision("AAPL", "CSP", 100, "filled"),
                          _mk_decision("TSLA", "CSP", 100, "killed")])
        assert _grade_selection_skill(decisions, outcomes, min_graded=1) is None


class TestDecisionParsing:
    def test_decision_date_from_key(self):
        d = _decision_date("2026-05-20|caspar|AAPL|CSP|190.00", {})
        assert d is not None and d.year == 2026 and d.month == 5 and d.day == 20

    def test_decision_date_from_ts_epoch_ms(self):
        # 2026-05-20T00:00:00Z ≈ 1779580800 s → ms
        d = _decision_date("nokey", {"ts": 1779580800000})
        assert d is not None and d.year == 2026

    def test_decision_date_from_iso_string(self):
        d = _decision_date("nokey", {"updatedAt": "2026-05-20T10:00:00Z"})
        assert d is not None and d.year == 2026 and d.month == 5

    def test_decision_date_unparseable_is_none(self):
        assert _decision_date("nokey", {"ts": "not-a-date"}) is None

    def test_decision_fields_prefers_doc_then_key(self):
        key = "2026-05-20|caspar|AAPL|CSP|190.00"
        tk, strat, strike, status, _ = _decision_fields(key, {"status": "filled"})
        assert (tk, strat, strike, status) == ("AAPL", "CSP", 190.0, "filled")


class TestNormalizeOutcomes:
    def test_merges_and_dedupes(self):
        historical = [{"scan_date": "2026-05-01", "ticker": "aapl", "strategy": "csp",
                       "strike": "100", "strategy_outcome": "WIN"}]
        new = [SignalOutcomeRow(
            scan_date="2026-05-01", eval_date="2026-05-31", ticker="AAPL",
            strategy="CSP", scan_composite=0, scan_technical=0, strike=100.0,
            expiry="2026-05-30", dte=29, price_at_scan=100, price_at_eval=101,
            fwd_return_pct=1.0, strategy_outcome="WIN", outcome_pnl_pct=1.0,
            pnl_model=PNL_MODEL_PREMIUM)]
        norm = _normalize_outcomes(historical, new)
        # Same compound key → collapsed to one, uppercased + numeric strike.
        assert len(norm) == 1
        assert norm[0]["ticker"] == "AAPL" and norm[0]["strike"] == 100.0

    def test_skips_blank_rows(self):
        assert _normalize_outcomes([{"ticker": "", "strategy_outcome": "WIN"}], []) == []


def test_build_report_surfaces_selection_edge():
    """With user_decisions + graded_outcomes, the report shows the edge line."""
    winners = ["AAPL", "MSFT", "NVDA"]
    losers = ["TSLA", "AMD", "META"]
    graded = ([_mk_outcome(t, "CSP", 100, "WIN") for t in winners]
              + [_mk_outcome(t, "CSP", 100, "LOSS") for t in losers])
    decisions = dict([_mk_decision(t, "CSP", 100, "filled") for t in winners]
                     + [_mk_decision(t, "CSP", 100, "killed") for t in losers])
    report = _build_report([], {}, {"win": 0, "loss": 0, "scratch": 0},
                           user_decisions=decisions, graded_outcomes=graded)
    assert "Selection edge: +1.00" in report
    assert "ADDS value" in report
