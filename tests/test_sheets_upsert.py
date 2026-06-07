"""Tests for src.sheets.upsert_tab — the ATOMIC full-tab overwrite helper.

upsert_tab replaces the non-atomic `ws.clear(); ws.update("A1", values)` idiom
with a SINGLE write call so the tab is never observably empty (a crash/429
between clear() and update() previously left dedup ledgers blank, re-firing
every alert). These tests mock the worksheet and assert:
  * clear() is NEVER called (no empty window)
  * exactly ONE update() write happens
  * the written block carries the new data AND blanks any stale trailing rows
    when shrinking, with value_input_option / start preserved.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src import sheets


def _make_ws(prior_rows: list[list[str]], col_count: int = 10) -> MagicMock:
    """Mock worksheet whose get_all_values() returns the prior occupied rows."""
    ws = MagicMock()
    ws.get_all_values.return_value = prior_rows
    ws.col_count = col_count
    ws.title = "MockTab"
    return ws


def _written(ws: MagicMock):
    """Return (values, range_name, value_input_option) from the single update()."""
    assert ws.update.call_count == 1, f"expected exactly 1 update(), got {ws.update.call_count}"
    args, kwargs = ws.update.call_args
    values = args[0]
    range_name = args[1] if len(args) > 1 else kwargs.get("range_name")
    vio = kwargs.get("value_input_option")
    return values, range_name, vio


def test_full_overwrite_same_size():
    """Same-size overwrite: one write, exact values, no clear(), no padding."""
    prior = [["h1", "h2"], ["a", "b"], ["c", "d"]]
    new = [["h1", "h2"], ["x", "y"], ["z", "w"]]
    ws = _make_ws(prior)

    sheets.upsert_tab(ws, new)

    ws.clear.assert_not_called()
    values, range_name, vio = _written(ws)
    assert values == new
    assert range_name == "A1"
    assert vio == "USER_ENTERED"


def test_shrinking_tab_erases_stale_tail():
    """Prior 4 rows, new 2 rows -> write must blank rows 3 and 4 in the SAME call."""
    prior = [["h1", "h2"], ["a", "b"], ["c", "d"], ["e", "f"]]
    new = [["h1", "h2"], ["x", "y"]]
    ws = _make_ws(prior)

    sheets.upsert_tab(ws, new)

    ws.clear.assert_not_called()
    values, _, _ = _written(ws)
    # First two rows are the new data; remaining two are blank padding (width 2).
    assert values[0] == ["h1", "h2"]
    assert values[1] == ["x", "y"]
    assert len(values) == 4, "must pad up to the prior row count to erase the tail"
    assert values[2] == ["", ""]
    assert values[3] == ["", ""]


def test_growing_tab_no_padding():
    """Prior 2 rows, new 4 rows -> write exactly the new block, no blank padding."""
    prior = [["h1", "h2"], ["a", "b"]]
    new = [["h1", "h2"], ["a", "b"], ["c", "d"], ["e", "f"]]
    ws = _make_ws(prior)

    sheets.upsert_tab(ws, new)

    ws.clear.assert_not_called()
    values, _, _ = _written(ws)
    assert values == new
    assert len(values) == 4


def test_empty_input_blanks_prior_range():
    """Empty values on a previously-populated tab -> one write of blank rows."""
    prior = [["h1", "h2"], ["a", "b"], ["c", "d"]]
    ws = _make_ws(prior)

    sheets.upsert_tab(ws, [])

    ws.clear.assert_not_called()
    values, range_name, _ = _written(ws)
    # Blanks all 3 prior rows in a single write; width falls back to col_count.
    assert len(values) == 3
    for row in values:
        assert all(cell == "" for cell in row)
        assert len(row) == 10  # col_count fallback
    assert range_name == "A1"


def test_empty_input_empty_tab_is_noop():
    """Empty values on an empty tab -> no write at all (avoids empty payload)."""
    ws = _make_ws([])
    sheets.upsert_tab(ws, [])
    ws.clear.assert_not_called()
    ws.update.assert_not_called()


def test_value_input_option_and_start_preserved():
    """RAW + custom start must be forwarded verbatim (cleanup_dupes uses RAW)."""
    prior = [["h"], ["a"]]
    new = [["h"], ["x"]]
    ws = _make_ws(prior)

    sheets.upsert_tab(ws, new, start="A1", value_input_option="RAW")

    values, range_name, vio = _written(ws)
    assert values == new
    assert range_name == "A1"
    assert vio == "RAW"


def test_ragged_rows_pad_to_widest():
    """Stale-tail blanking width tracks the widest written row, not row 0."""
    prior = [["h1", "h2", "h3"], ["a", "b", "c"], ["d", "e", "f"]]
    # New data: header width 2, but a data row width 3 -> blanking width must be 3.
    new = [["h1", "h2"], ["a", "b", "c"]]
    ws = _make_ws(prior)

    sheets.upsert_tab(ws, new)

    values, _, _ = _written(ws)
    assert len(values) == 3  # padded up to prior 3 rows
    assert values[2] == ["", "", ""]  # blank row width matches widest (3)
