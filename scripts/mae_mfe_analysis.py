#!/usr/bin/env python3
"""
MAE/MFE excursion analysis over the Alpaca paper book (the engine's own trades).

WHY THIS EXISTS
---------------
The systematic engine has fixed entry logic but no measured exit discipline. It
closes on mechanical rules (50% / 21-DTE) that were never checked against what
the trades actually *did* while open. This script measures, per position, the
best (MFE) and worst (MAE) it reached versus where it ended — surfacing winners
that round-tripped back to losers ("given back") and quantifying what a
profit-take rule would have changed.

DATA
----
Reads the ``positions_alpaca`` tab: one daily snapshot row per open position,
carrying ``upl_pct`` (unrealised P&L %, percent units). We group rows into one
chronological path per (ticker, side), then reduce each path with
:mod:`src.mae_mfe`. Positions with <3 daily marks are skipped (no real path).

This is the paper book on purpose: it is the engine's *own* executed trades —
the thing Caspar asked to have verified — and the only book with enough mark
history today. The real IBKR options book can be added once it has turnover.

USAGE
-----
  python scripts/mae_mfe_analysis.py            # report + write `mae_mfe` tab
  python scripts/mae_mfe_analysis.py --dry      # report only, no sheet write
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sheets as sh  # noqa: E402
from src.sync import load_env  # noqa: E402
from src.mae_mfe import (  # noqa: E402
    compute_excursions,
    is_option,
    whatif_bracket,
    whatif_profit_take,
)

SOURCE_TAB = "positions_alpaca"
MIN_MARKS = 3  # need at least 3 daily marks for a meaningful path
MEANINGFUL_MFE = 5.0  # only count "given back" for trades that cleared +5%
TAKE_THRESHOLDS = (25.0, 50.0, 100.0)
BRACKET = (50.0, -30.0)  # (take, stop) for the two-sided what-if


@dataclass
class PositionResult:
    ticker: str
    instrument: str  # "option" | "stock"
    status: str  # "CLOSED" | "open"
    n_marks: int
    first_date: str
    last_date: str
    mfe: float
    mae: float
    exit: float
    given_back: float
    capture: float | None
    cost_basis: float | None
    given_back_usd: float | None
    path: list[float]

    TAB_NAME = "mae_mfe"
    HEADERS = [
        "ticker", "instrument", "status", "n_marks", "first_date", "last_date",
        "mfe_pct", "mae_pct", "exit_pct", "given_back_pct", "capture_pct",
        "cost_basis", "given_back_usd",
    ]

    def to_row(self) -> list[str]:
        def f(x: float | None, nd: int = 1) -> str:
            return "" if x is None else f"{x:.{nd}f}"

        return [
            self.ticker, self.instrument, self.status, str(self.n_marks),
            self.first_date, self.last_date,
            f(self.mfe), f(self.mae), f(self.exit), f(self.given_back),
            "" if self.capture is None else f"{self.capture * 100:.0f}",
            f(self.cost_basis, 2), f(self.given_back_usd, 2),
        ]


def _num(x: str) -> float | None:
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def build_results(rows: list[dict]) -> list[PositionResult]:
    """Reconstruct per-(ticker, side) paths from snapshot rows and reduce them.

    NOTE: one path per (ticker, side) over the whole window — a ticker closed
    and re-entered would merge into a single path. Acceptable for the current
    short history; revisit if re-entries become common.
    """
    all_days = sorted({(r.get("date") or "")[:10] for r in rows if r.get("date")})
    latest = all_days[-1] if all_days else ""

    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if not r.get("date") or not r.get("ticker"):
            continue
        groups.setdefault((r["ticker"], r.get("side", "")), []).append(r)

    results: list[PositionResult] = []
    for (ticker, _side), grp in groups.items():
        grp.sort(key=lambda r: r["date"])
        path = [_num(r.get("upl_pct")) for r in grp]
        path = [p for p in path if p is not None]
        if len(path) < MIN_MARKS:
            continue

        exc = compute_excursions(path)

        # Book cost is invariant: cost = mkt_val - upl on any snapshot day.
        first = grp[0]
        mkt_val, upl = _num(first.get("mkt_val")), _num(first.get("upl"))
        cost = abs(mkt_val - upl) if (mkt_val is not None and upl is not None) else None
        if cost is not None and cost <= 0:
            cost = None
        gb_usd = (exc.given_back / 100.0) * cost if cost else None

        last_seen = max((r["date"] or "")[:10] for r in grp)
        results.append(
            PositionResult(
                ticker=ticker,
                instrument="option" if is_option(ticker) else "stock",
                status="CLOSED" if last_seen < latest else "open",
                n_marks=len(path),
                first_date=(grp[0]["date"] or "")[:10],
                last_date=last_seen,
                mfe=exc.mfe, mae=exc.mae, exit=exc.exit,
                given_back=exc.given_back, capture=exc.capture,
                cost_basis=cost, given_back_usd=gb_usd,
                path=path,
            )
        )
    return results


def _whatif_table(results: list[PositionResult]) -> list[tuple[str, float, float]]:
    """Equal-weight mean realised upl_pct under each exit rule vs holding.

    Equal-weighted (each trade counts once) so it reads as "the average trade's
    realised return" rather than a size-weighted P&L. Returns
    (label, mean_pct, delta_vs_hold) rows.
    """
    paths = [r.path for r in results]
    hold = st.mean(p[-1] for p in paths)
    out = [("Hold to exit / now", hold, 0.0)]
    for t in TAKE_THRESHOLDS:
        m = st.mean(whatif_profit_take(p, t) for p in paths)
        out.append((f"Take profit @ +{t:.0f}%", m, m - hold))
    take, stop = BRACKET
    mb = st.mean(whatif_bracket(p, take=take, stop=stop) for p in paths)
    out.append((f"Bracket +{take:.0f}% / {stop:.0f}%", mb, mb - hold))
    return out


def render_report(results: list[PositionResult], window: tuple[str, str, int]) -> str:
    first_day, last_day, n_days = window
    opts = [r for r in results if r.instrument == "option"]
    stks = [r for r in results if r.instrument == "stock"]
    L: list[str] = []
    L.append("MAE/MFE EXCURSION ANALYSIS — Alpaca paper book (the engine's own trades)")
    L.append(f"Source: {SOURCE_TAB} | window: {first_day} → {last_day} ({n_days} snapshot days)")
    L.append(f"Positions with >={MIN_MARKS} daily marks: {len(results)} "
             f"({len(opts)} options, {len(stks)} stocks)")
    L.append("")
    L.append(f"[!] EARLY SAMPLE — {len(results)} positions over ~{n_days} trading days. "
             "Directional, not statistical.")
    L.append("    The picture sharpens automatically as snapshot history accumulates.")
    L.append("")

    winners = [r for r in results if r.mfe >= MEANINGFUL_MFE]
    L.append("THE FINDING — profit reached vs profit kept")
    if winners:
        gb = [r.given_back for r in winners]
        caps = [r.capture for r in winners if r.capture is not None]
        usd = [r.given_back_usd for r in winners if r.given_back_usd is not None]
        L.append(f"  Positions that reached >={MEANINGFUL_MFE:.0f}% profit: {len(winners)}")
        L.append(f"  Given back from peak — median {st.median(gb):.0f} pts, mean {st.mean(gb):.0f} pts")
        if caps:
            L.append(f"  Capture (fraction of peak kept) — median {st.median(caps) * 100:.0f}%")
        if usd:
            L.append(f"  Est. $ surrendered from peaks: ${sum(usd):,.0f} "
                     f"(across {len(usd)} sized positions)")
    else:
        L.append("  No position cleared +5% MFE in this window.")
    L.append("")

    def _tbl(title: str, items: list[PositionResult]) -> None:
        L.append(title)
        L.append(f"  {'ticker':18}{'MFE':>8}{'MAE':>8}{'exit/now':>10}"
                 f"{'gaveback':>10}{'$back':>10}  status")
        for r in items:
            usd = "" if r.given_back_usd is None else f"-${abs(r.given_back_usd):,.0f}"
            L.append(f"  {r.ticker:18}{r.mfe:>7.0f}%{r.mae:>7.0f}%{r.exit:>9.0f}%"
                     f"{r.given_back:>8.0f}pts{usd:>10}  {r.status}")
        L.append("")

    by_gb = sorted(winners, key=lambda r: -r.given_back)
    _tbl("WORST ROUND-TRIPS (rode the peak back down)", by_gb[:8])

    well = sorted([r for r in winners if r.capture is not None],
                  key=lambda r: -(r.capture or 0))
    _tbl("WELL MANAGED (kept most of the peak)", well[:5])

    L.append("WHAT-IF — exit rule vs the engine's current hold behaviour (equal-weight mean return)")
    for label, mean_pct, delta in _whatif_table(results):
        d = "  —" if delta == 0 else f"{delta:+.0f} pts"
        L.append(f"  {label:24}{mean_pct:>8.1f}%   {d}")
    L.append("")

    # Honest verdict: separate the ROBUST signal (do take-profits beat holding,
    # is a tight stop destructive) from the FRAGILE one (the exact best
    # threshold, which a few option outliers swing on this small sample).
    table = _whatif_table(results)
    takes = table[1:-1]  # take-profit rows
    bracket_row = table[-1]  # the two-sided bracket (last row)
    take_deltas = [d for _, _, d in takes]
    if take_deltas and all(d > 0 for d in take_deltas):
        L.append(f"VERDICT: every take-profit threshold beat holding "
                 f"(+{min(take_deltas):.0f} to +{max(take_deltas):.0f} pts/trade) — the engine "
                 f"surrenders real profit for lack of a take rule. The exact best threshold is "
                 f"outlier-sensitive on this sample; the robust signal is simply 'take profits'.")
        if bracket_row[2] < 0:
            L.append(f"         The naive {bracket_row[0]} LOST {bracket_row[2]:+.0f} pts (a tight stop "
                     f"whipsaws out of high-vol names that later recover) — add a take-profit, not a stop.")
    else:
        L.append("VERDICT: no take-profit rule clearly beats holding on this sample yet — let history grow.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true", help="Print report, no sheet write")
    args = ap.parse_args()

    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)
    raw = ss.worksheet(SOURCE_TAB).get_all_values()
    if not raw:
        print(f"{SOURCE_TAB} is empty — nothing to analyse.")
        return 1
    hdr, data = raw[0], raw[1:]
    rows = [dict(zip(hdr, r)) for r in data if any(r)]

    days = sorted({(r.get("date") or "")[:10] for r in rows if r.get("date")})
    window = (days[0] if days else "-", days[-1] if days else "-", len(days))

    results = build_results(rows)
    results.sort(key=lambda r: -r.given_back)

    print(render_report(results, window))

    if args.dry:
        print(f"\n[DRY] Would write {len(results)} rows to '{PositionResult.TAB_NAME}'.")
        return 0

    ws = sh.ensure_headers(client, PositionResult.TAB_NAME, PositionResult.HEADERS)
    sh.upsert_tab(ws, [PositionResult.HEADERS] + [r.to_row() for r in results])
    print(f"\nWrote {len(results)} rows to '{PositionResult.TAB_NAME}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
