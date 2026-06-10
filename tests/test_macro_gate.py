"""Tests for the fail-SAFE macro gate (2026-06-08/09 incident fixes).

Covers:
  • Source ordering: own `macro` Sheet tab FIRST, yfinance FALLBACK
  • Latest row selected by PARSED timestamp, never rows[-1] (append-unordered tab)
  • Both sources dead → regime=CAUTION + degraded=True (never STANDARD constant)
  • gex_regime SELL_CAUTION / exposure_posture CASH_PRIORITY overlay:
    regime ≥ CAUTION, premium-selling candidates tagged + sizing halved
  • Existing HALTED logic stands (VIX>30 OR SPX<200dma)
  • MacroRow schema: spx_above_200sma appended LAST (legacy alignment)
  • macro_grab 200dma computation
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.daily_options_scan as dos  # noqa: E402
from src.macro_blackouts import MacroFeed  # noqa: E402

log = logging.getLogger("test-macro-gate")

MACRO_HDR = ["date", "vix", "dxy", "us_10y", "spx", "usd_sgd", "spx_above_200sma"]
GEX_HDR = ["date", "symbol", "spot", "net_gex", "gamma_flip", "flip_distance_pct",
           "call_wall", "put_wall", "regime", "premium_gate", "note", "updated_at"]
POSTURE_HDR = ["date", "exposure_ceiling_pct", "bias", "participation",
               "recommendation", "confidence", "rationale", "components_json"]


class _WS:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class _SS:
    """Minimal gspread Spreadsheet stand-in: worksheet(name).get_all_values()."""
    def __init__(self, tabs: dict[str, list[list[str]]]):
        self._tabs = tabs

    def worksheet(self, name):
        if name not in self._tabs:
            raise Exception(f"worksheet {name} not found")
        return _WS(self._tabs[name])


def _ts(hours_ago: float = 0.0) -> str:
    """Fresh audit timestamp (the macro tab's THHMMSS-suffixed format)."""
    return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H%M%S")


def _macro_row(date: str, vix: str, spx: str = "6000.00", spx_above: str = "TRUE"):
    return [date, vix, "100.0", "4.40", spx, "1.3000", spx_above]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Gate tests never hit the network: blackout feed empty, yfinance dead
    unless a test overrides the helpers explicitly."""
    monkeypatch.setattr(MacroFeed, "fetch", classmethod(lambda cls, **kw: MacroFeed()))
    monkeypatch.setattr(dos, "_yf_vix", lambda logger: None)
    monkeypatch.setattr(dos, "_yf_spx_200dma", lambda logger: (None, None, None))


# ── timestamp parsing / latest-row selection ────────────────────────────────

def test_parse_audit_ts_formats():
    assert dos._parse_audit_ts("2026-06-09T180409") == datetime(2026, 6, 9, 18, 4, 9)
    assert dos._parse_audit_ts("2026-06-09 18:04:09") == datetime(2026, 6, 9, 18, 4, 9)
    assert dos._parse_audit_ts("2026-06-09T18:04:09") == datetime(2026, 6, 9, 18, 4, 9)
    assert dos._parse_audit_ts("2026-06-09") == datetime(2026, 6, 9)
    assert dos._parse_audit_ts("") is None
    assert dos._parse_audit_ts("garbage") is None


def test_latest_by_parsed_ts_not_physical_last():
    # The proven failure shape: 2026-06-09T180409 physically PRECEDES T005009.
    rows = [
        {"date": "2026-06-09T180409", "vix": "21.81"},   # chronologically latest
        {"date": "2026-06-09T005009", "vix": "19.87"},   # physically last
    ]
    assert dos._latest_by_parsed_ts(rows)["vix"] == "21.81"


def test_latest_by_parsed_ts_skips_unparseable_and_handles_empty():
    assert dos._latest_by_parsed_ts([]) is None
    rows = [{"date": "junk"}, {"date": "2026-06-01", "vix": "15"}]
    assert dos._latest_by_parsed_ts(rows)["vix"] == "15"


# ── source ordering: sheet first, yfinance fallback ─────────────────────────

def test_gate_reads_macro_tab_first_latest_by_parsed_ts(monkeypatch):
    def _boom(logger):  # yfinance must NOT be consulted when the sheet has data
        raise AssertionError("yfinance called despite healthy macro tab")
    monkeypatch.setattr(dos, "_yf_vix", _boom)

    ss = _SS({"macro": [
        MACRO_HDR,
        _macro_row(_ts(hours_ago=2), "21.81"),    # chronologically latest, physically FIRST
        _macro_row(_ts(hours_ago=20), "19.87"),   # physically last (older)
    ]})
    r = dos.macro_gate(log, ss=ss)
    assert r["vix"] == 21.8
    assert r["vix_source"] == "macro_tab"
    assert r["degraded"] is False
    assert r["spx_above_200sma"] is True
    assert r["regime"] == "STANDARD" and not r["halted"]


def test_gate_falls_back_to_yfinance_when_tab_empty(monkeypatch):
    monkeypatch.setattr(dos, "_yf_vix", lambda logger: 18.5)
    monkeypatch.setattr(dos, "_yf_spx_200dma", lambda logger: (6000.0, 5800.0, True))
    ss = _SS({"macro": [MACRO_HDR]})    # header only
    r = dos.macro_gate(log, ss=ss)
    assert r["vix"] == 18.5 and r["vix_source"] == "yfinance"
    assert r["degraded"] is False and r["regime"] == "STANDARD"


def test_gate_stale_macro_tab_falls_back(monkeypatch):
    monkeypatch.setattr(dos, "_yf_vix", lambda logger: 17.0)
    monkeypatch.setattr(dos, "_yf_spx_200dma", lambda logger: (6000.0, 5800.0, True))
    ss = _SS({"macro": [MACRO_HDR, _macro_row(_ts(hours_ago=24 * 6), "25.0")]})  # 6 days old
    r = dos.macro_gate(log, ss=ss)
    assert r["vix"] == 17.0 and r["vix_source"] == "yfinance"


def test_gate_both_sources_dead_fails_safe_to_caution():
    """THE incident fix: no data may never print STANDARD from a constant."""
    ss = _SS({})    # every tab read raises; yfinance helpers return None (fixture)
    r = dos.macro_gate(log, ss=ss)
    assert r["regime"] == "CAUTION" and r["caution"] is True
    assert r["degraded"] is True
    assert r["vix"] is None and r["vix_source"] is None
    assert r["halted"] is False     # degraded ≠ halted (tag + halve, not zero-out)


def test_gate_no_ss_and_dead_yfinance_is_degraded_caution():
    r = dos.macro_gate(log, ss=None)
    assert r["regime"] == "CAUTION" and r["degraded"] is True


def test_gate_partial_data_vix_only_is_degraded(monkeypatch):
    """VIX known but SPX-vs-200dma unknowable → still degraded (halt input
    unverifiable) — exactly the June 8-9 shape once the sheet carries VIX."""
    ss = _SS({"macro": [
        MACRO_HDR[:6],                                           # legacy 6-col tab
        [_ts(1), "21.81", "100.0", "4.40", "6000.00", "1.30"],   # no spx_above col
    ]})
    r = dos.macro_gate(log, ss=ss)
    assert r["vix"] == 21.8 and r["vix_source"] == "macro_tab"
    assert r["degraded"] is True
    assert r["regime"] == "CAUTION"


def test_gate_merges_fields_across_writers(monkeypatch):
    """daily_tracker / sync rows don't carry spx_above_200sma — a tracker row
    landing LAST must not mask macro_grab's flag (else permanent degradation)."""
    def _boom(logger):
        raise AssertionError("yfinance called despite mergeable sheet data")
    monkeypatch.setattr(dos, "_yf_vix", _boom)
    monkeypatch.setattr(dos, "_yf_spx_200dma", _boom)

    ss = _SS({"macro": [
        MACRO_HDR,
        _macro_row(_ts(hours_ago=10), "20.50", spx_above="TRUE"),          # macro_grab row
        [_ts(hours_ago=1), "21.81", "100.0", "4.40", "6000.0", "1.30"],    # tracker row, NEWEST, no flag
    ]})
    r = dos.macro_gate(log, ss=ss)
    assert r["vix"] == 21.8                       # newest VIX (tracker row)
    assert r["spx_above_200sma"] is True          # flag survives from the grab row
    assert r["degraded"] is False and r["regime"] == "STANDARD"


def test_merge_macro_rows_ignores_stale_field_values():
    rows = [
        {"date": _ts(hours_ago=24 * 10), "vix": "33.0", "spx_above_200sma": "FALSE"},  # ancient
        {"date": _ts(hours_ago=1), "vix": "18.0"},
    ]
    merged = dos.merge_macro_rows(rows)
    assert merged["vix"] == 18.0
    assert "spx_above_200sma" not in merged       # 10-day-old flag is NOT trusted
    assert dos.merge_macro_rows([rows[0]]) == {}  # all-stale → {} → yfinance fallback


# ── HALTED logic stands ──────────────────────────────────────────────────────

def test_gate_halts_on_high_vix_from_sheet():
    ss = _SS({"macro": [MACRO_HDR, _macro_row(_ts(1), "35.0")]})
    r = dos.macro_gate(log, ss=ss)
    assert r["regime"] == "HALTED" and r["halted"] is True


def test_gate_halts_on_spx_below_200dma_from_sheet():
    ss = _SS({"macro": [MACRO_HDR, _macro_row(_ts(1), "12.0", spx_above="FALSE")]})
    r = dos.macro_gate(log, ss=ss)
    assert r["regime"] == "HALTED" and r["halted"] is True


def test_gate_caution_on_vix_25_to_30():
    ss = _SS({"macro": [MACRO_HDR, _macro_row(_ts(1), "27.0")]})
    r = dos.macro_gate(log, ss=ss)
    assert r["regime"] == "CAUTION" and not r["halted"]


# ── gex_regime / exposure_posture overlay ───────────────────────────────────

def _healthy_macro_tab():
    return [MACRO_HDR, _macro_row(_ts(1), "18.0")]


def test_gate_sell_caution_overlay_forces_caution():
    ss = _SS({
        "macro": _healthy_macro_tab(),
        "gex_regime": [
            GEX_HDR,
            [_ts(3), "QQQ", "530", "1e9", "525", "0.9", "540", "510",
             "POSITIVE_PINNED", "SELL_OK", "", _ts(3)],
            [_ts(2), "SPY", "600", "-12.4e9", "612", "-2.0", "620", "590",
             "NEGATIVE_TREND", "SELL_CAUTION", "short gamma", _ts(2)],
        ],
    })
    r = dos.macro_gate(log, ss=ss)
    assert r["premium_gate"] == "SELL_CAUTION" and r["sell_caution"] is True
    assert r["regime"] == "CAUTION"


def test_gate_cash_priority_overlay_forces_caution():
    ss = _SS({
        "macro": _healthy_macro_tab(),
        "exposure_posture": [
            POSTURE_HDR,
            [_ts(30), "60", "NEUTRAL", "BROAD", "NEW_ENTRY_ALLOWED", "HIGH", "", "{}"],
            [_ts(2), "25", "VALUE", "NARROW", "CASH_PRIORITY", "HIGH", "risk-off", "{}"],
        ],
    })
    r = dos.macro_gate(log, ss=ss)
    assert r["posture"] == "CASH_PRIORITY" and r["cash_priority"] is True
    assert r["posture_ceiling"] == 25.0
    assert r["regime"] == "CAUTION"


def test_gate_latest_spy_gex_row_wins_not_physical_last():
    ss = _SS({
        "macro": _healthy_macro_tab(),
        "gex_regime": [
            GEX_HDR,
            [_ts(2), "SPY", "600", "1e9", "590", "1.7", "620", "590",
             "POSITIVE_PINNED", "SELL_OK", "", _ts(2)],         # latest, physically first
            [_ts(26), "SPY", "598", "-9e9", "610", "-2.0", "620", "585",
             "NEGATIVE_TREND", "SELL_CAUTION", "", _ts(26)],    # older, physically last
        ],
    })
    r = dos.macro_gate(log, ss=ss)
    assert r["premium_gate"] == "SELL_OK" and r["sell_caution"] is False
    assert r["regime"] == "STANDARD"


# ── candidate tagging + sizing halving ──────────────────────────────────────

def _cand(strategy="CSP", notes=""):
    return {"strategy": strategy, "ticker": "NVDA", "strike": 100.0,
            "underlying_last": 112.0, "premium": 1.50, "cash_required": 500.0,
            "notes": notes}


def test_apply_macro_warnings_tags_premium_selling_only():
    macro = {"sell_caution": True, "cash_priority": True}
    cands = [_cand("CSP", notes="d0.25"), _cand("IC", notes="SP:90/LP:85/SC:110/LC:115 W:$5"),
             _cand("HARVEST_CSP"), _cand("LONG_CALL", notes="gov catalyst")]
    n = dos._apply_macro_warnings(cands, macro)
    assert n == 3
    assert cands[0]["notes"] == "⚠ SELL_CAUTION ⚠ CASH_PRIORITY | d0.25"
    assert cands[1]["notes"].startswith("⚠ SELL_CAUTION ⚠ CASH_PRIORITY | SP:90")
    assert cands[2]["notes"] == "⚠ SELL_CAUTION ⚠ CASH_PRIORITY"
    assert cands[3]["notes"] == "gov catalyst"          # debit strategy untouched


def test_apply_macro_warnings_keeps_spread_legs_parseable():
    """The executor regex-parses leg strikes out of notes — tags must not break it."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ex_for_tag_test", ROOT / "scripts" / "alpaca_paper_execute.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    c = _cand("IC", notes="SP:90/LP:85/SC:110/LC:115 W:$5")
    dos._apply_macro_warnings([c], {"sell_caution": True})
    assert ex.parse_leg_strikes(c["notes"]) == {"SP": 90, "LP": 85, "SC": 110, "LC": 115}


def test_apply_macro_warnings_noop_when_clear():
    cands = [_cand("CSP", notes="d0.25")]
    assert dos._apply_macro_warnings(cands, {"sell_caution": False, "cash_priority": False}) == 0
    assert cands[0]["notes"] == "d0.25"


_STATES = {"caspar": {"nlv": 100_000.0, "is_margin": True, "profile": "aggressive",
                      "excess_liq": None}}


def test_sizing_note_normal_unhalved():
    note = dos._sizing_note(_cand("CSP"), _STATES, {"vix": 15.0, "spx_above_200sma": True})
    assert note.startswith("size C:") and "→" not in note and "HALVED" not in note


def test_sizing_note_halves_when_degraded():
    normal = dos._sizing_note(_cand("CSP"), _STATES, {"vix": 15.0, "spx_above_200sma": True})
    n = int(normal.split("C:")[1].split("x")[0])
    assert n >= 2, "fixture must size to ≥2 contracts for a meaningful halve"
    degraded = dos._sizing_note(
        _cand("CSP"), _STATES,
        {"vix": None, "spx_above_200sma": True, "degraded": True})
    assert f"C:{n}x→{n // 2}x" in degraded
    assert "HALVED: MACRO_DEGRADED" in degraded


def test_sizing_note_halves_premium_selling_on_sell_caution_not_long_call():
    macro = {"vix": 15.0, "spx_above_200sma": True, "sell_caution": True}
    csp = dos._sizing_note(_cand("CSP"), _STATES, macro)
    assert "HALVED: SELL_CAUTION" in csp and "→" in csp
    lc = dos._sizing_note(_cand("LONG_CALL"), _STATES, macro)
    assert "HALVED" not in lc and "→" not in lc


# ── MacroRow schema: column appended LAST ───────────────────────────────────

def test_macro_row_schema_appends_spx_above_last():
    from src.schema import MacroRow
    assert MacroRow.HEADERS[-1] == "spx_above_200sma"
    assert MacroRow.HEADERS[:6] == ["date", "vix", "dxy", "us_10y", "spx", "usd_sgd"]
    r_true = MacroRow(date="2026-06-10", vix=18.0, spx_above_200sma=True).to_row(audit=False)
    r_false = MacroRow(date="2026-06-10", vix=18.0, spx_above_200sma=False).to_row(audit=False)
    r_none = MacroRow(date="2026-06-10", vix=18.0).to_row(audit=False)
    assert len(r_true) == len(MacroRow.HEADERS)
    assert r_true[-1] == "TRUE" and r_false[-1] == "FALSE" and r_none[-1] == ""


def test_macro_from_ledger_passthrough():
    from src.schema.macro import macro_from_ledger
    row = macro_from_ledger({"macro": {"vix": 19.0, "spx_above_200sma": True}}, "2026-06-10")
    assert row.spx_above_200sma is True
    row2 = macro_from_ledger({"macro": {"vix": 19.0}}, "2026-06-10")
    assert row2.spx_above_200sma is None


# ── macro_grab 200dma helper ────────────────────────────────────────────────

def test_spx_above_200dma_from_closes():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "macro_grab", ROOT / "scripts" / "macro_grab.py")
    mg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mg)
    up = list(range(1, 251))                       # ends well above its 200dma
    assert mg.spx_above_200dma_from_closes([float(x) for x in up]) is True
    down = [float(x) for x in range(250, 0, -1)]   # ends well below
    assert mg.spx_above_200dma_from_closes(down) is False
    assert mg.spx_above_200dma_from_closes([1.0] * 100) is None   # not enough history
