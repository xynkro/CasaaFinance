"""
Maximum Adverse / Favorable Excursion (MAE/MFE) analysis.

Each position carries a chronological path of daily unrealised-P&L percentages
(``upl_pct`` from the ``positions_alpaca`` snapshots, already in percent units:
``12.5`` means +12.5%). From that path we measure how a trade *behaved while it
was open* — not just how it ended:

  * **MFE** — the best the position ever reached (max upl_pct).
  * **MAE** — the worst it ever reached (min upl_pct).
  * **exit** — the last observed upl_pct (realised for a closed position; the
    current mark for one still open).
  * **given_back** — ``MFE - exit``: profit the trade REACHED but did not keep.
  * **capture** — ``exit / MFE`` when ``MFE > 0``: the fraction of the peak
    retained (1.0 = kept it all, 0 = round-tripped to flat, <0 = peak turned
    into a loss).

The headline question this answers for the systematic engine: do winners get
ridden back to losers because there is no profit-take discipline? On the live
paper book the answer was yes — the median position that reached >5% profit
gave back ~29 points of it (see ``scripts/mae_mfe_analysis.py``).

Pure functions only: no I/O, no Sheets. The CLI feeds these the snapshot paths.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.alpaca import parse_occ_symbol


def is_option(ticker: str) -> bool:
    """True when ``ticker`` is an OCC option symbol (e.g. ``PSN260618C00050000``).

    Reuses the canonical parser in :mod:`src.alpaca` so option detection here
    can never drift from how the rest of the system reads OCC symbols.
    """
    return parse_occ_symbol(ticker) is not None


@dataclass(frozen=True)
class Excursions:
    """Excursion summary of one position's daily upl_pct path (percent units)."""

    mfe: float
    mae: float
    exit: float
    given_back: float
    capture: float | None


def compute_excursions(path: list[float]) -> Excursions:
    """Reduce a chronological ``upl_pct`` path (oldest→newest) to its excursions.

    ``path`` must be non-empty. ``capture`` is ``None`` when the position was
    never above water (``MFE <= 0``), since "fraction of peak kept" is undefined
    with no positive peak.
    """
    if not path:
        raise ValueError("path must be non-empty")
    mfe = max(path)
    mae = min(path)
    exit_ = path[-1]
    given_back = mfe - exit_
    capture = (exit_ / mfe) if mfe > 0 else None
    return Excursions(
        mfe=mfe, mae=mae, exit=exit_, given_back=given_back, capture=capture
    )


def whatif_profit_take(path: list[float], threshold: float) -> float:
    """Realised upl_pct under a "close on first daily mark at/above +threshold%" rule.

    We fill at the *daily mark* that first crossed the threshold, not the
    unobservable intraday peak — conservative, so it never overstates the rule's
    benefit. If the path never reached the threshold, the trade is held to its
    end and realises ``path[-1]``.
    """
    if not path:
        raise ValueError("path must be non-empty")
    for v in path:
        if v >= threshold:
            return v
    return path[-1]


def whatif_bracket(path: list[float], *, take: float, stop: float) -> float:
    """Realised upl_pct under a two-sided bracket: take-profit OR stop-loss.

    Walks the path oldest→newest and exits on the first daily mark that touches
    either bound (``>= take`` or ``<= stop``), realising that day's value. If
    neither bound is ever hit, the trade is held to its end (``path[-1]``).
    Per-day the value is a single number, so the two bounds can't both fire on
    the same mark — whichever is touched first chronologically wins.
    """
    if not path:
        raise ValueError("path must be non-empty")
    for v in path:
        if v >= take or v <= stop:
            return v
    return path[-1]
