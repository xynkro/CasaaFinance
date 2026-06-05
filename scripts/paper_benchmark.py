#!/usr/bin/env python3
"""
paper_benchmark.py — "did the active book beat just holding SPY?"

The whole strategy debate is answerable empirically: for every paper position
the auto-trader took, compare its P&L to what the SAME capital would have made
in SPY over the SAME holding window. Summed up, that's the honest alpha — and
because we benchmark DEPLOYED capital (not raw account NLV), it isn't drowned by
the paper account's idle cash.

Capital base per position:
  • equity / long option → what you actually paid (|cost_basis|)
  • short option (CSP/CC/spread leg) → notional risk (strike × 100 × contracts),
    since the real alternative was to put that cash-secured amount into SPY.

Writes paper_benchmark (one row per position + a TOTAL) and prints the verdict.
Read-only against Alpaca + yfinance; the burden of proof is on the active book.

Usage:
  python scripts/paper_benchmark.py --dry
  python scripts/paper_benchmark.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ──────────────────── Pure math (tested) ────────────────────────────────────

def capital_base(cost_basis: float, occ: dict | None, qty: float) -> float:
    """Capital the position actually tied up — the fair base for an SPY-equivalent."""
    if occ is None:                       # equity
        return abs(cost_basis)
    if qty < 0:                           # short option → cash-secured / notional risk
        return float(occ["strike"]) * 100.0 * abs(qty)
    return abs(cost_basis)                # long option → premium paid


def spy_equiv_pl(capital: float, spy_return_pct: float) -> float:
    """P&L the same capital would have made in SPY over the window."""
    return capital * spy_return_pct / 100.0


def position_alpha(position_pl: float, capital: float, spy_return_pct: float) -> dict:
    se = spy_equiv_pl(capital, spy_return_pct)
    return {"spy_equiv": round(se, 2), "alpha": round(position_pl - se, 2),
            "beat": position_pl > se}


def mf_sleeve_alpha(rows: list, mf_tickers: set) -> dict | None:
    """Aggregate the Motley Fool sleeve vs SPY from per-position benchmark rows.
    Ignores the TOTAL / MF_SLEEVE summary rows; matches by ticker. Returns None when
    no MF position is held — so 'is the $499/yr sleeve beating SPY?' is always
    isolatable from the rest of the shared paper book."""
    want = {t.upper() for t in mf_tickers}
    mf = [r for r in rows
          if str(getattr(r, "ticker", "")).upper() in want
          and str(getattr(r, "ticker", "")).upper() not in ("TOTAL", "MF_SLEEVE")]
    if not mf:
        return None
    pl = round(sum(float(r.position_pl) for r in mf), 2)
    equiv = round(sum(float(r.spy_equiv_pl) for r in mf), 2)
    return {"position_pl": pl, "spy_equiv_pl": equiv,
            "alpha_pl": round(pl - equiv, 2), "beat_spy": (pl - equiv) > 0, "n": len(mf)}


def _mf_core_tickers(ss) -> set:
    """Tickers in the MF core sleeve — daily_plan rows with leg=mf_core (latest day)."""
    try:
        vals = ss.worksheet("daily_plan").get_all_values()
    except Exception:
        return set()
    if len(vals) < 2:
        return set()
    rows = [dict(zip(vals[0], r)) for r in vals[1:] if any(r)]
    dates = {(r.get("date") or "")[:10] for r in rows if r.get("date")}
    if not dates:
        return set()
    latest = max(dates)
    return {(r.get("ticker") or "").upper() for r in rows
            if (r.get("date") or "")[:10] == latest and (r.get("leg") or "") == "mf_core"}


def spy_return_since(spy_by_date: dict, entry_date: str, today: str) -> float:
    """% SPY return from entry → today, using the close on-or-before each date."""
    def close_on_or_before(d: str) -> float:
        keys = sorted(k for k in spy_by_date if k <= d)
        return spy_by_date[keys[-1]] if keys else 0.0
    e = close_on_or_before(entry_date)
    n = close_on_or_before(today)
    return ((n / e) - 1) * 100 if e > 0 and n > 0 else 0.0


# ──────────────────── I/O ────────────────────────────────────────────────────

def _entry_dates(orders: list[dict]) -> dict:
    """Earliest fill date per symbol (the position's entry)."""
    out: dict[str, str] = {}
    for o in orders:
        sym = o.get("symbol", "")
        ts = o.get("filled_at") or o.get("submitted_at") or ""
        d = str(ts)[:10]
        if sym and d and (sym not in out or d < out[sym]):
            out[sym] = d
    return out


def _spy_series(start: str) -> dict:
    import yfinance as yf
    hist = yf.Ticker("SPY").history(start=start, interval="1d", auto_adjust=True)
    if hist.empty:
        return {}
    return {d.strftime("%Y-%m-%d"): float(c)
            for d, c in zip(hist.index, hist["Close"]) if c == c}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print only, no sheet write")
    args = ap.parse_args()

    from src.sync import load_env
    from src import alpaca, schema as S
    load_env()

    today = date.today().isoformat()
    try:
        positions = alpaca.get_positions()
        orders = alpaca.get_orders(status="all", limit=500)
    except Exception as e:
        print(f"Alpaca read failed: {e}")
        return 1

    # Attribution: this paper account is shared (ZeroDTE 0-DTE SPY bot + an
    # untagged decision-queue executor trade here too). Benchmark ONLY the
    # automated FinancePWA book — positions whose symbol was placed by a
    # casaa-tagged order — so "did the book beat SPY?" measures our picks, not
    # someone else's. Falls back to all positions if no tagged orders are found.
    owned = alpaca.financepwa_symbols(orders)
    if owned:
        external = [p for p in positions if p.get("symbol", "") not in owned]
        positions = [p for p in positions if p.get("symbol", "") in owned]
        if external:
            print(f"(excluded {len(external)} non-FinancePWA positions from the "
                  f"benchmark: {', '.join(sorted({p.get('symbol','') for p in external}))})")

    entry = _entry_dates(orders)
    start = min([entry.get(p.get("symbol", ""), today) for p in positions] + [today])
    spy = _spy_series(start) if positions else {}

    rows, tot_pl, tot_equiv = [], 0.0, 0.0
    beat = 0
    print(f"=== Paper book vs SPY · {today} · {len(positions)} positions ===\n")
    for p in positions:
        sym = p.get("symbol", "")
        occ = alpaca.parse_occ_symbol(sym)
        qty = float(p.get("qty", 0) or 0)
        cb = float(p.get("cost_basis", 0) or 0)
        pl = float(p.get("unrealized_pl", 0) or 0)
        edate = entry.get(sym, today)
        days = (datetime.fromisoformat(today) - datetime.fromisoformat(edate)).days
        spy_ret = spy_return_since(spy, edate, today)
        cap = capital_base(cb, occ, qty)
        pa = position_alpha(pl, cap, spy_ret)
        tot_pl += pl
        tot_equiv += pa["spy_equiv"]
        if pa["beat"]:
            beat += 1
        label = occ["underlying"] if occ else sym
        flag = "BEAT" if pa["beat"] else "lag "
        print(f"  {flag} {label:6} {days:3}d  P&L {pl:+8.2f}  vs SPY {pa['spy_equiv']:+8.2f}  "
              f"α {pa['alpha']:+8.2f}  (SPY {spy_ret:+.1f}%)")
        rows.append(S.PaperBenchmarkRow(
            date=today, ticker=sym, entry_date=edate, days_held=max(days, 0),
            cost_basis=round(cap, 2), position_pl=round(pl, 2),
            spy_return_pct=round(spy_ret, 2), spy_equiv_pl=pa["spy_equiv"],
            alpha_pl=pa["alpha"], beat_spy=pa["beat"]))

    total_alpha = round(tot_pl - tot_equiv, 2)
    n = len(positions)
    print(f"\n  {'═'*60}")
    print(f"  BOOK: P&L {tot_pl:+.2f}  ·  SPY-equivalent {tot_equiv:+.2f}  ·  "
          f"ALPHA {total_alpha:+.2f}")
    print(f"  {beat}/{n} positions beat SPY  →  the book is "
          f"{'BEATING' if total_alpha > 0 else 'LAGGING'} the index.")
    rows.append(S.PaperBenchmarkRow(
        date=today, ticker="TOTAL", entry_date="", days_held=0,
        cost_basis=0.0, position_pl=round(tot_pl, 2), spy_return_pct=0.0,
        spy_equiv_pl=round(tot_equiv, 2), alpha_pl=total_alpha, beat_spy=total_alpha > 0))

    if args.dry or not rows:
        print(f"\n[{'DRY' if args.dry else 'NO-OP'}] {len(rows)} benchmark rows.")
        return 0

    from src import sheets as sh
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    # MF sleeve isolation — "is the Motley Fool sleeve beating SPY?" (the accountability
    # layer: separately measurable from the rest of the shared book).
    mf = mf_sleeve_alpha(rows, _mf_core_tickers(ss))
    if mf:
        print(f"  MF SLEEVE: P&L {mf['position_pl']:+.2f} · SPY-equiv {mf['spy_equiv_pl']:+.2f} "
              f"· α {mf['alpha_pl']:+.2f}  ({mf['n']} names)")
        rows.append(S.PaperBenchmarkRow(
            date=today, ticker="MF_SLEEVE", entry_date="", days_held=0, cost_basis=0.0,
            position_pl=mf["position_pl"], spy_return_pct=0.0, spy_equiv_pl=mf["spy_equiv_pl"],
            alpha_pl=mf["alpha_pl"], beat_spy=mf["beat_spy"]))

    sh.ensure_headers(client, S.PaperBenchmarkRow.TAB_NAME, S.PaperBenchmarkRow.HEADERS)
    # Replace today's rows (idempotent re-run), keep history.
    ws = ss.worksheet(S.PaperBenchmarkRow.TAB_NAME)
    existing = ws.get_all_values()
    keep = [existing[0]] if existing else [S.PaperBenchmarkRow.HEADERS]
    keep += [r for r in (existing[1:] if existing else []) if r and r[0][:10] != today]
    keep += [r.to_row() for r in rows]
    ws.clear()
    ws.update("A1", keep, value_input_option="USER_ENTERED")
    print(f"\n✓ Wrote {len(rows)} rows to paper_benchmark")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
