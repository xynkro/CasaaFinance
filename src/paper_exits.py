"""
Autonomous exit management for the Alpaca PAPER executor.

The scanner-executor opens short-premium positions but historically never closed
them — so winners round-tripped (MAE/MFE showed the median position gave back
~29 points of its peak, ~$28k paper surrendered). This module supplies the
missing discipline as pure, testable logic:

  * take profit at 50% of max  (captured >= 0.50 of the entry credit),
  * stop at 2x credit          (captured <= -2.0),
  * mechanical close at <=21 DTE.

SAFETY: plan_exits only ever emits an intent for a symbol in ``casaa_syms`` — the
set of option legs FinancePWA itself opened (client_order_id prefix ``casaa-``,
see :func:`src.alpaca.financepwa_symbols`). It therefore can NEVER close a
position belonging to another bot in the shared paper account (e.g. ZeroDTE's
SPY 0-DTE). It also only touches SHORT option legs (qty < 0); equities and long
options pass through untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.alpaca import parse_occ_symbol

TAKE_PROFIT = 0.50   # close short premium at 50% of max profit
STOP_MULT = -2.0     # stop when the loss reaches 2x the credit received
DTE_FLOOR = 21       # mechanical close/roll at <=21 DTE


def exit_action(
    captured_pct: float, dte: int | None, *,
    take_profit: float = TAKE_PROFIT, stop_mult: float = STOP_MULT,
    dte_floor: int = DTE_FLOOR,
) -> str | None:
    """The mechanical exit decision for one short-premium leg (None = hold).

    ``captured_pct`` is the fraction of the entry credit captured: +0.50 == 50%
    of max profit banked; -2.0 == the leg has lost 2x the credit received.
    Take-profit and stop-loss are mutually exclusive; the DTE rule is the
    fallback for a still-open, not-yet-at-target leg.
    """
    if captured_pct >= take_profit:
        return "take_profit"
    if captured_pct <= stop_mult:
        return "stop"
    if dte is not None and dte <= dte_floor:
        return "dte_close"
    return None


@dataclass(frozen=True)
class ExitIntent:
    symbol: str          # OCC option symbol to close
    qty: int             # positive number of contracts to buy-to-close
    action: str          # take_profit | stop | dte_close
    captured_pct: float
    dte: int | None


def _num(x) -> float | None:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _dte(expiry: str, today: date) -> int | None:
    try:
        y, m, d = (int(p) for p in expiry.split("-"))
        return (date(y, m, d) - today).days
    except (ValueError, AttributeError):
        return None


def plan_exits(
    positions: list[dict], casaa_syms: set[str], *, today: date,
) -> list[ExitIntent]:
    """Exit intents for FinancePWA's OWN short-premium legs only.

    A position is eligible only when ALL hold: its symbol is in ``casaa_syms``
    (we opened it), it parses as an OCC option, and qty < 0 (a short leg). Any
    other position — someone else's, an equity, a long option — is skipped.
    """
    out: list[ExitIntent] = []
    for p in positions or []:
        sym = str(p.get("symbol", "") or "")
        if sym not in casaa_syms:
            continue  # SAFETY: never touch a leg we did not open
        occ = parse_occ_symbol(sym)
        if not occ:
            continue  # equities / non-option symbols pass through
        qty = _num(p.get("qty"))
        if qty is None or qty >= 0:
            continue  # short premium only
        entry = _num(p.get("avg_entry_price"))
        cur = _num(p.get("current_price"))
        if entry is None or cur is None or entry <= 0:
            continue
        captured = (entry - cur) / entry  # short: mark below credit → positive
        dte = _dte(occ["expiry"], today)
        act = exit_action(captured, dte)
        if act:
            out.append(ExitIntent(sym, int(abs(qty)), act, round(captured, 4), dte))
    return out
