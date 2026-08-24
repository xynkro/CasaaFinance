"""Regression: replace_today_rows must dedup regardless of runner timezone.

Root cause (2026-08-24): rows are stamped SGT (`now_sgt_iso`) but the helper
compared against `date.today()`, which on a UTC GitHub runner is a day BEHIND
during US market hours (21:30-04:00 SGT). Every grab in that window therefore
failed to match its own date prefix and silently appended instead of replacing —
positions_sarah accumulated 10x duplicate rows per ticker per day (180 rows for
18 tickers), which inflated every downstream sum tenfold.

Fix: derive the prefix from the batch being written, not from the wall clock.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import sheets as sh


class _WS:
    """Minimal worksheet double capturing what upsert_tab would write."""

    def __init__(self, values):
        self._values = [list(r) for r in values]
        self.appended = []

    def get_all_values(self):
        return [list(r) for r in self._values]

    def append_rows(self, rows, value_input_option=None):
        self.appended.extend(rows)

    col_count = 6


def _patch(monkeypatch, ws):
    monkeypatch.setattr(sh, "_open_sheet", lambda client: type(
        "SS", (), {"worksheet": staticmethod(lambda name: ws)})())
    written = {}
    monkeypatch.setattr(sh, "upsert_tab",
                        lambda w, values, **kw: written.update(values=values))
    return written


HDR = ["date", "ticker", "mkt_val"]


def test_dedups_sgt_rows_when_runner_clock_is_a_day_behind(monkeypatch):
    """The exact failure: SGT-stamped rows, UTC runner one day back."""
    existing = [HDR,
                ["2026-08-21T230000", "AAPL", "100"],   # genuine prior day — keep
                ["2026-08-22T004435", "AAPL", "110"],   # today's earlier grab — replace
                ["2026-08-22T013749", "AAPL", "111"]]   # today's earlier grab — replace
    ws = _WS(existing)
    written = _patch(monkeypatch, ws)
    # Runner clock says 08-21 (UTC) while the batch is stamped 08-22 (SGT).
    monkeypatch.setattr(sh, "_today_iso", lambda: "2026-08-21", raising=False)
    n = sh.replace_today_rows(None, "positions_sarah",
                              [["2026-08-22T060000", "AAPL", "120"]])
    rows = written["values"]
    assert n == 1
    assert rows[0] == HDR
    dates = [r[0] for r in rows[1:]]
    assert "2026-08-21T230000" in dates            # prior day preserved
    assert not any(d.startswith("2026-08-22T0044") for d in dates)  # dupes gone
    assert not any(d.startswith("2026-08-22T0137") for d in dates)
    assert sum(1 for d in dates if d.startswith("2026-08-22")) == 1  # exactly one


def test_explicit_prefix_still_wins(monkeypatch):
    ws = _WS([HDR, ["2026-08-20T010000", "X", "1"], ["2026-08-22T010000", "Y", "2"]])
    written = _patch(monkeypatch, ws)
    sh.replace_today_rows(None, "t", [["2026-08-22T020000", "Z", "3"]],
                          today_prefix="2026-08-20")
    dates = [r[0] for r in written["values"][1:]]
    assert not any(d.startswith("2026-08-20") for d in dates)  # the named day cleared
    assert any(d.startswith("2026-08-22T010000") for d in dates)  # others untouched


def test_empty_batch_falls_back_to_clock_and_still_clears(monkeypatch):
    ws = _WS([HDR, ["2026-08-22T010000", "Y", "2"]])
    written = _patch(monkeypatch, ws)
    n = sh.replace_today_rows(None, "t", [], today_prefix="2026-08-22")
    assert n == 0
    assert written["values"] == [HDR]


def test_multi_row_batch_uses_the_batch_date(monkeypatch):
    ws = _WS([HDR,
              ["2026-08-22T010000", "A", "1"],
              ["2026-08-22T010000", "B", "2"],
              ["2026-08-19T010000", "OLD", "9"]])
    written = _patch(monkeypatch, ws)
    batch = [["2026-08-22T090000", "A", "5"], ["2026-08-22T090000", "B", "6"]]
    n = sh.replace_today_rows(None, "t", batch)
    dates = [r[0] for r in written["values"][1:]]
    assert n == 2
    assert sum(1 for d in dates if d.startswith("2026-08-22")) == 2  # not 4
    assert "2026-08-19T010000" in dates                              # history kept


def test_ragged_first_row_does_not_crash(monkeypatch):
    ws = _WS([HDR, ["2026-08-22T010000", "A", "1"]])
    written = _patch(monkeypatch, ws)
    sh.replace_today_rows(None, "t", [[""]])  # empty date cell → fall back, no crash
    assert "values" in written
