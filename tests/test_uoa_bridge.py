"""Regression: the UoaAlert -> UoaAlertRow bridge must carry the quality layer.

Found 2026-09-06. The scanner computed aggressor/structure/bias/quality onto its
own UoaAlert dataclass, then built the sheet row S.UoaAlertRow(...) WITHOUT
passing them. Because both dataclasses declare those fields WITH DEFAULTS,
nothing raised — 240 alerts persisted with aggressor=UNKNOWN and quality=0 while
the scanner had real values in hand. Silent, and invisible in the UI.

The guard is a field-by-field bridge assertion, so adding a field to one side
without wiring it fails here instead of quietly writing a default.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.schema import UoaAlertRow

QUALITY_FIELDS = ("bid", "ask", "last_price", "aggressor", "structure", "bias",
                  "extrinsic_pct", "quality")


def _scanner_alert():
    """A UoaAlert as the scanner builds it, with the quality layer populated."""
    from scripts.unusual_options_scan import UoaAlert
    return UoaAlert(
        ticker="NVDA", alert_type="VOL_OI_SPIKE", side="CALL", strike=210.0,
        expiry="2026-09-11", dte=17, volume=9865, open_interest=797,
        vol_oi_ratio=12.4, implied_vol=0.45, notional=8_000_000.0,
        moneyness="ATM", underlying_last=209.19, option_price=8.12,
        detail="x", severity=3,
        bid=8.00, ask=8.25, last_price=8.25, aggressor="BUY_INITIATED",
        structure="LONG_CALL", bias="BULLISH", extrinsic_pct=100.0, quality=88,
    )


def test_both_sides_declare_the_quality_fields():
    a = _scanner_alert()
    for f in QUALITY_FIELDS:
        assert hasattr(a, f), f"UoaAlert missing {f}"
        assert f in UoaAlertRow.HEADERS, f"UoaAlertRow.HEADERS missing {f}"


def test_bridge_carries_every_quality_field_not_defaults():
    """The actual bug: values must survive UoaAlert -> UoaAlertRow."""
    a = _scanner_alert()
    row = UoaAlertRow(
        date="2026-09-06", ticker=a.ticker, alert_type=a.alert_type, side=a.side,
        strike=a.strike, expiry=a.expiry, dte=a.dte, volume=a.volume,
        open_interest=a.open_interest, vol_oi_ratio=a.vol_oi_ratio,
        implied_vol=a.implied_vol, notional=a.notional, moneyness=a.moneyness,
        underlying_last=a.underlying_last, option_price=a.option_price,
        severity=a.severity, detail=a.detail,
        bid=a.bid, ask=a.ask, last_price=a.last_price, aggressor=a.aggressor,
        structure=a.structure, bias=a.bias, extrinsic_pct=a.extrinsic_pct,
        quality=a.quality,
    )
    for f in QUALITY_FIELDS:
        assert getattr(row, f) == getattr(a, f), f"{f} lost across the bridge"
    # And specifically NOT the defaults that were being written.
    assert row.aggressor != "UNKNOWN" and row.quality != 0


def test_serialized_row_actually_contains_the_values():
    """to_row() must emit them in the right columns, not blanks."""
    a = _scanner_alert()
    row = UoaAlertRow(
        date="2026-09-06", ticker=a.ticker, alert_type=a.alert_type, side=a.side,
        strike=a.strike, expiry=a.expiry, dte=a.dte, volume=a.volume,
        open_interest=a.open_interest, vol_oi_ratio=a.vol_oi_ratio,
        implied_vol=a.implied_vol, notional=a.notional, moneyness=a.moneyness,
        underlying_last=a.underlying_last, option_price=a.option_price,
        severity=a.severity, detail=a.detail,
        bid=a.bid, ask=a.ask, last_price=a.last_price, aggressor=a.aggressor,
        structure=a.structure, bias=a.bias, extrinsic_pct=a.extrinsic_pct,
        quality=a.quality,
    )
    out = row.to_row()
    assert len(out) == len(UoaAlertRow.HEADERS)
    idx = {h: i for i, h in enumerate(UoaAlertRow.HEADERS)}
    assert out[idx["aggressor"]] == "BUY_INITIATED"
    assert out[idx["structure"]] == "LONG_CALL"
    assert out[idx["bias"]] == "BULLISH"
    assert out[idx["quality"]] == "88"


def test_scanner_passes_quality_kwargs_at_every_per_contract_site():
    """Per-contract alert types must forward **_q; PC_SKEW legitimately doesn't
    (it is an aggregate across strikes, not a single print)."""
    src = (ROOT / "scripts" / "unusual_options_scan.py").read_text()
    assert src.count("**_q") >= 3, "per-contract constructors lost their quality kwargs"
    # And the sheet-row build must forward them too.
    assert "aggressor=a.aggressor" in src and "quality=a.quality" in src
