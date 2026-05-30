"""Tests for src/realized_premium.py — wheel realized-premium accounting (F3).
Emphasis on the conservatism contract: never over-count, never raise basis."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.realized_premium import (  # noqa: E402
    new_trades, realized_option_premium_per_share, option_key,
)


def _opt(time, sym, side, strike, price, qty=1, expiry="20260101", right="P", mult=100):
    return {"time": time, "symbol": sym, "sec_type": "OPT", "side": side,
            "right": right, "strike": strike, "expiry": expiry, "qty": qty,
            "price": price, "multiplier": mult}


def _stk(time, sym, side, price, qty=100):
    return {"time": time, "symbol": sym, "sec_type": "STK", "side": side,
            "right": "", "strike": "", "expiry": "", "qty": qty, "price": price}


# ── dedup ────────────────────────────────────────────────────────────────────

def test_new_trades_dedup():
    existing = [_opt("t1", "X", "SLD", 100, 1.5)]
    candidates = [_opt("t1", "X", "SLD", 100, 1.5),   # dupe
                  _opt("t2", "X", "BOT", 100, 0.5)]   # new
    out = new_trades(existing, candidates)
    assert len(out) == 1 and out[0]["time"] == "t2"


def test_dedup_survives_sheet_format_roundtrip():
    # The sheet stores numbers formatted ("95.00", "1", "1.5100") while the grab
    # has floats (95.0, 1.0, 1.51). Dedup MUST treat them as the same fill, or
    # every fill is re-appended daily.
    grab_fill = _opt("2026-05-01T10:00", "X", "SLD", 95.0, 1.51, qty=1.0)
    persisted = {"time": "2026-05-01T10:00", "account": "", "symbol": "X",
                 "sec_type": "OPT", "side": "SLD", "right": "P", "strike": "95.00",
                 "expiry": "20260101", "qty": "1", "price": "1.5100"}
    out = new_trades([persisted], [grab_fill])
    assert out == []   # recognized as already persisted


# ── realized premium ─────────────────────────────────────────────────────────

def test_closed_put_premium_reduces_basis():
    # Sold a put for $1.50 that's no longer open -> $150 / 100sh = $1.50/share.
    trades = [_opt("t1", "X", "SLD", 95, 1.50)]
    prem = realized_option_premium_per_share(trades, "X", shares=100)
    assert prem == 1.50


def test_open_leg_excluded_to_avoid_double_count():
    # The only option is currently OPEN -> excluded -> 0 (daily_tracker credits it).
    trades = [_opt("t1", "X", "SLD", 95, 1.50, expiry="20260612")]
    prem = realized_option_premium_per_share(
        trades, "X", shares=100, open_option_keys={option_key("P", 95, "20260612")})
    assert prem == 0.0


def test_buyback_nets_against_credit():
    # Sold for 1.50, bought back for 0.40 -> net 1.10 -> $110/100 = $1.10/share.
    trades = [_opt("t1", "X", "SLD", 95, 1.50), _opt("t2", "X", "BOT", 95, 0.40)]
    prem = realized_option_premium_per_share(trades, "X", shares=100)
    assert abs(prem - 1.10) < 1e-9


def test_net_loss_returns_zero_never_raises_basis():
    # Bought back for MORE than collected -> net negative -> 0 (never raise basis).
    trades = [_opt("t1", "X", "SLD", 95, 0.50), _opt("t2", "X", "BOT", 95, 2.00)]
    prem = realized_option_premium_per_share(trades, "X", shares=100)
    assert prem == 0.0


def test_prior_position_premium_excluded_by_holding_scope():
    # Premium collected BEFORE the most recent stock buy belongs to a prior
    # position and must NOT reduce the current basis (the over-count danger).
    trades = [
        _opt("2026-01-01", "X", "SLD", 95, 5.00),   # old cycle, before re-entry
        _stk("2026-03-01", "X", "BOT", 100),         # re-acquired shares here
        _opt("2026-03-05", "X", "SLD", 90, 1.20),   # current-cycle premium
    ]
    prem = realized_option_premium_per_share(trades, "X", shares=100)
    assert abs(prem - 1.20) < 1e-9   # only the post-re-entry $1.20, NOT the $5.00


def test_zero_shares_returns_zero():
    trades = [_opt("t1", "X", "SLD", 95, 1.50)]
    assert realized_option_premium_per_share(trades, "X", shares=0) == 0.0


def test_other_ticker_ignored():
    trades = [_opt("t1", "Y", "SLD", 95, 1.50)]
    assert realized_option_premium_per_share(trades, "X", shares=100) == 0.0
