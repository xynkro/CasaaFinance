"""Tests for the post-audit scan policy changes (2026-08-20).

Two findings from grading 2,328 evaluated recommendations drove these:

  1. Defined-risk spreads lose systematically — PCS 36% win / -4.7% avg fwd,
     CCS 40% / -3.5%, IC 39% / -3.6%, negative in EVERY month scanned. They are
     disabled by default (re-enable with SPREADS_ENABLED=true).
  2. `composite_score` is ANTI-predictive — highest-score quartile averaged
     -1.77% forward return vs +1.62% for the lowest, correlation -0.089. So
     ranking no longer uses it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.daily_options_scan import filter_disabled_strategies, ranking_key


def _cands():
    return [
        {"ticker": "NVDA", "strategy": "PCS", "annual_yield_pct": 40.0, "composite_score": 90},
        {"ticker": "AAPL", "strategy": "CSP", "annual_yield_pct": 18.0, "composite_score": 30},
        {"ticker": "MSFT", "strategy": "CC", "annual_yield_pct": 12.0, "composite_score": 80},
        {"ticker": "AMD", "strategy": "IC", "annual_yield_pct": 55.0, "composite_score": 99},
        {"ticker": "META", "strategy": "CCS", "annual_yield_pct": 33.0, "composite_score": 70},
        {"ticker": "PLTR", "strategy": "LONG_CALL", "annual_yield_pct": 0.0, "composite_score": 50},
        {"ticker": "TSLA", "strategy": "HARVEST_CSP", "annual_yield_pct": 25.0, "composite_score": 60},
    ]


class TestSpreadDisable:
    def test_spreads_dropped_by_default(self):
        kept, n = filter_disabled_strategies(_cands(), spreads_enabled=False)
        assert n == 3  # PCS + IC + CCS
        assert {c["strategy"] for c in kept} == {"CSP", "CC", "LONG_CALL", "HARVEST_CSP"}

    def test_wheel_and_debit_survive(self):
        kept, _ = filter_disabled_strategies(_cands(), spreads_enabled=False)
        tickers = {c["ticker"] for c in kept}
        assert {"AAPL", "MSFT", "PLTR", "TSLA"} <= tickers
        assert not ({"NVDA", "AMD", "META"} & tickers)

    def test_flag_re_enables_spreads(self):
        kept, n = filter_disabled_strategies(_cands(), spreads_enabled=True)
        assert n == 0
        assert len(kept) == len(_cands())

    def test_case_insensitive_and_safe_on_junk(self):
        odd = [{"ticker": "X", "strategy": "pcs"}, {"ticker": "Y"}, {"ticker": "Z", "strategy": None}]
        kept, n = filter_disabled_strategies(odd, spreads_enabled=False)
        assert n == 1 and len(kept) == 2  # lowercase pcs dropped; missing/None kept

    def test_empty_list(self):
        assert filter_disabled_strategies([], spreads_enabled=False) == ([], 0)


class TestRankingIgnoresComposite:
    def test_ranks_by_yield_not_composite(self):
        # AAPL has the LOWEST composite (30) but a higher yield than MSFT (80).
        aapl = {"annual_yield_pct": 18.0, "composite_score": 30}
        msft = {"annual_yield_pct": 12.0, "composite_score": 80}
        assert ranking_key(aapl) > ranking_key(msft)

    def test_composite_has_no_effect_on_rank(self):
        lo = {"annual_yield_pct": 20.0, "composite_score": 1}
        hi = {"annual_yield_pct": 20.0, "composite_score": 99}
        assert ranking_key(lo) == ranking_key(hi)

    def test_missing_or_junk_yield_sorts_last(self):
        assert ranking_key({}) == 0.0
        assert ranking_key({"annual_yield_pct": None}) == 0.0
        assert ranking_key({"annual_yield_pct": "abc"}) == 0.0

    def test_sorting_a_list_puts_best_yield_first(self):
        cs = sorted(_cands(), key=ranking_key, reverse=True)
        assert cs[0]["ticker"] == "AMD"  # 55% yield despite being ranked on yield alone
