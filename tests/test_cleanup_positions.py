"""Tests for scripts.cleanup_positions_dupes — historical duplicate removal.

This tool overwrites the source-of-truth Sheet, so the pure selection logic is
tested hard before it is ever allowed to write.

Contract: within each calendar day, keep ONLY the rows from that day's LATEST
write-time (the freshest complete snapshot) and drop the earlier partial repeats
the timezone bug left behind. Rows whose date cannot be parsed are KEPT — we
never delete data we don't understand.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cleanup_positions_dupes import keep_latest_write_per_day, summarise


def _r(ts, ticker, val="1"):
    return [ts, ticker, val]


def test_keeps_only_the_latest_write_group_for_a_day():
    rows = [
        _r("2026-08-22T004435", "AAPL"), _r("2026-08-22T004435", "AMD"),
        _r("2026-08-22T055239", "AAPL"), _r("2026-08-22T055239", "AMD"),
    ]
    kept = keep_latest_write_per_day(rows)
    assert len(kept) == 2
    assert {r[0] for r in kept} == {"2026-08-22T055239"}
    assert {r[1] for r in kept} == {"AAPL", "AMD"}


def test_preserves_every_distinct_day():
    rows = [
        _r("2026-08-21T010000", "AAPL"), _r("2026-08-21T090000", "AAPL"),
        _r("2026-08-22T010000", "AAPL"), _r("2026-08-22T090000", "AAPL"),
    ]
    kept = keep_latest_write_per_day(rows)
    assert len(kept) == 2
    assert sorted(r[0] for r in kept) == ["2026-08-21T090000", "2026-08-22T090000"]


def test_single_write_day_is_untouched():
    rows = [_r("2026-08-20T010000", "AAPL"), _r("2026-08-20T010000", "AMD")]
    assert keep_latest_write_per_day(rows) == rows


def test_row_order_within_the_kept_group_is_stable():
    rows = [_r("2026-08-22T090000", "Z"), _r("2026-08-22T090000", "A"),
            _r("2026-08-22T010000", "Q")]
    assert [r[1] for r in keep_latest_write_per_day(rows)] == ["Z", "A"]


def test_unparseable_dates_are_kept_never_dropped():
    rows = [_r("", "GHOST"), _r("not-a-date", "GHOST2"),
            _r("2026-08-22T010000", "AAPL"), _r("2026-08-22T090000", "AAPL")]
    kept = keep_latest_write_per_day(rows)
    tickers = {r[1] for r in kept}
    assert "GHOST" in tickers and "GHOST2" in tickers
    assert sum(1 for r in kept if r[1] == "AAPL") == 1


def test_date_only_stamps_without_time_still_collapse():
    rows = [_r("2026-08-22", "AAPL"), _r("2026-08-22", "AMD")]
    assert len(keep_latest_write_per_day(rows)) == 2


def test_empty_input():
    assert keep_latest_write_per_day([]) == []


def test_ragged_rows_do_not_crash():
    assert keep_latest_write_per_day([[], ["2026-08-22T010000"]]) is not None


def test_summarise_reports_the_real_shape():
    rows = [_r(f"2026-08-22T00{i:04d}", t) for i in range(3) for t in ("A", "B")]
    s = summarise(rows, keep_latest_write_per_day(rows))
    assert s["before"] == 6 and s["after"] == 2 and s["removed"] == 4
    assert s["days"] == 1
    assert s["worst_day"][1] == 3          # 3 write-times on that day


def test_summarise_on_clean_data_reports_no_removal():
    rows = [_r("2026-08-22T010000", "A"), _r("2026-08-21T010000", "A")]
    s = summarise(rows, keep_latest_write_per_day(rows))
    assert s["removed"] == 0 and s["days"] == 2
