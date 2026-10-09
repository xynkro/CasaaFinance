"""Hold list — positions Caspar has decided to keep regardless of what the
engine thinks.

2026-10-09: shown that OPEN, BBAI, SLV and RCAT were more than all of his real
losses, Caspar said "if its already loser dont realize those losses by selling
just leave it." The engine had been queueing OPEN TRIM since 2026-09-21 and
would keep doing so every day. This module makes the decision durable: any
(account, ticker) on the `hold_list` tab is exempt from SELL-side
recommendations — TRIM and CC — in the decision queue, in Telegram alerts, and
anywhere else that would nag. Buying more is not blocked; only reducing.

The list lives in the SHEET, not in source. This repo is public, and a ticker
list in code is a holdings disclosure. The tab is hand-editable: add a row to
put a name on hold, delete the row to take it off. account "*" holds a ticker
for every account.

Reads FAIL OPEN: if the tab is missing or unreadable, nothing is suppressed.
A missing list must never hide a real alert by accident; the cost of failing
open is one extra nag, the cost of failing closed is a missed page.
"""
from __future__ import annotations

from typing import Callable, Iterable, TypeVar

HOLD_LIST_TAB = "hold_list"

# Strategies that reduce or exit an existing position. A hold means "do not
# propose these for this name".
HOLD_SELL_STRATEGIES = frozenset({"TRIM", "CC"})

T = TypeVar("T")


def hold_key(account, ticker) -> tuple[str, str]:
    """Normalised (account, ticker) — case- and whitespace-insensitive."""
    return (str(account or "").strip().lower(), str(ticker or "").strip().upper())


def is_sell_rec(strategy) -> bool:
    return str(strategy or "").strip().upper() in HOLD_SELL_STRATEGIES


def is_held(account, ticker, holds: set[tuple[str, str]]) -> bool:
    if not holds:
        return False
    a, t = hold_key(account, ticker)
    if not t:
        return False
    return (a, t) in holds or ("*", t) in holds


def read_hold_list(ss) -> set[tuple[str, str]]:
    """(account, ticker) pairs from the hold_list tab of an open spreadsheet.

    Missing tab, empty tab, or missing columns → empty set (fail open).
    """
    try:
        vals = ss.worksheet(HOLD_LIST_TAB).get_all_values()
    except Exception:
        return set()
    if not vals:
        return set()
    hdr = [str(h).strip().lower() for h in vals[0]]
    try:
        ia, it = hdr.index("account"), hdr.index("ticker")
    except ValueError:
        return set()
    out: set[tuple[str, str]] = set()
    for r in vals[1:]:
        if len(r) <= max(ia, it):
            continue
        k = hold_key(r[ia], r[it])
        if k[1]:
            out.add(k)
    return out


def drop_held_sell_recs(
    items: Iterable[T],
    holds: set[tuple[str, str]],
    *,
    account: Callable[[T], object],
    ticker: Callable[[T], object],
    strategy: Callable[[T], object],
) -> tuple[list[T], list[T]]:
    """Split `items` into (kept, dropped): dropped = sell-side recs on held names.

    Shape-agnostic on purpose — the brain emits dicts, trigger_alerts builds
    Decision dataclasses; both call this with their own accessors.
    """
    kept: list[T] = []
    dropped: list[T] = []
    for it in items:
        if is_sell_rec(strategy(it)) and is_held(account(it), ticker(it), holds):
            dropped.append(it)
        else:
            kept.append(it)
    return kept, dropped
