#!/usr/bin/env python3
"""
Grade the UOA directional read before anything is traded on it.

The quality layer (src/uoa_quality.py) turns "a PUT traded" into LONG_PUT
(bearish) or SHORT_PUT (bullish). That is a claim about future prices, so it
gets graded exactly like the scan policy was: BULLISH-tagged names should
out-return BEARISH-tagged ones. If they don't, the read is noise and we find
that out cheaply instead of by losing money.

METHOD
  For each alert carrying a `bias`, take the underlying at the alert date and
  again `--horizon` days later (prices come from scan_results, which stores
  underlying_last daily per ticker). "Correct" means the move went the way the
  bias implied. Reported by bias and by quality bucket, because the whole point
  of the score is that high-quality prints should grade better than low.

HONEST LIMITATION
  `bias` was added 2026-08-25. It depends on bid/ask/lastPrice, which were
  fetched but discarded before that date, so there is NOTHING to backfill —
  grading is forward-only and starts empty. An empty result is the correct
  output today, not a bug.

USAGE
  python scripts/uoa_grade.py [--horizon 5] [--telegram]
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sheets as sh  # noqa: E402
from src.sync import load_env  # noqa: E402


def _f(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def build_price_index(scan_rows: list[dict]) -> dict[tuple[str, str], float]:
    """(ticker, YYYY-MM-DD) → underlying price, from the daily scan history."""
    out: dict[tuple[str, str], float] = {}
    for r in scan_rows:
        tk = (r.get("ticker") or "").upper()
        d = (r.get("date") or "")[:10]
        p = _f(r.get("underlying_last"))
        if tk and d and p and p > 0:
            out[(tk, d)] = p
    return out


def price_on_or_after(prices: dict, ticker: str, day: str, max_slip: int = 5
                      ) -> tuple[str, float] | None:
    """First available price at/after `day` (markets close, data gaps happen)."""
    try:
        y, m, dd = (int(x) for x in day.split("-"))
    except (ValueError, AttributeError):
        return None
    for i in range(max_slip + 1):
        k = (ticker.upper(), (date(y, m, dd) + timedelta(days=i)).isoformat())
        if k in prices:
            return k[1], prices[k]
    return None


def grade(alerts: list[dict], prices: dict, horizon: int) -> list[dict]:
    """One graded record per alert that has a usable bias and both prices."""
    out = []
    for a in alerts:
        bias = (a.get("bias") or "").upper()
        if bias not in ("BULLISH", "BEARISH"):
            continue                      # UNKNOWN/UNCLEAR carries no claim
        tk = (a.get("ticker") or "").upper()
        d0 = (a.get("date") or "")[:10]
        p0 = price_on_or_after(prices, tk, d0, 0)
        if not p0:
            continue
        try:
            y, m, dd = (int(x) for x in d0.split("-"))
        except ValueError:
            continue
        p1 = price_on_or_after(prices, tk, (date(y, m, dd) + timedelta(days=horizon)).isoformat())
        if not p1:
            continue
        ret = (p1[1] / p0[1] - 1) * 100
        correct = (ret > 0) if bias == "BULLISH" else (ret < 0)
        out.append({"ticker": tk, "date": d0, "bias": bias,
                    "quality": int(_f(a.get("quality")) or 0),
                    "structure": a.get("structure") or "",
                    "fwd_pct": ret, "correct": correct,
                    "signed_pct": ret if bias == "BULLISH" else -ret})
    return out


def render(graded: list[dict], horizon: int, n_alerts: int) -> str:
    L = [f"UOA GRADE — does the directional read predict? ({horizon}d horizon)", ""]
    if not graded:
        L.append(f"  {n_alerts} alerts scanned, 0 gradeable.")
        L.append("  `bias` was added 2026-08-25 and cannot be backfilled (bid/ask were")
        L.append("  never stored before then), so grading is forward-only. Come back")
        L.append("  once the scanner has written a few weeks of tagged alerts.")
        return "\n".join(L)
    L.append(f"  graded: {len(graded)} of {n_alerts} alerts")
    L.append("")
    L.append(f"  {'bias':10}{'n':>5}{'hit%':>8}{'avg signed%':>14}")
    by = defaultdict(list)
    for g in graded:
        by[g["bias"]].append(g)
    for b, g in sorted(by.items()):
        hit = sum(1 for x in g if x["correct"]) / len(g) * 100
        L.append(f"  {b:10}{len(g):>5}{hit:>7.0f}%{st.mean(x['signed_pct'] for x in g):>13.2f}%")
    L.append("")
    L.append("  by quality bucket (the score should separate signal from noise):")
    L.append(f"  {'bucket':10}{'n':>5}{'hit%':>8}{'avg signed%':>14}")
    buckets = [("0-39", 0, 39), ("40-59", 40, 59), ("60-79", 60, 79), ("80+", 80, 1000)]
    for name, lo, hi in buckets:
        g = [x for x in graded if lo <= x["quality"] <= hi]
        if not g:
            continue
        hit = sum(1 for x in g if x["correct"]) / len(g) * 100
        L.append(f"  {name:10}{len(g):>5}{hit:>7.0f}%{st.mean(x['signed_pct'] for x in g):>13.2f}%")
    overall = st.mean(x["signed_pct"] for x in graded)
    hit = sum(1 for x in graded if x["correct"]) / len(graded) * 100
    L.append("")
    if hit > 55 and overall > 0:
        L.append(f"  VERDICT: {hit:.0f}% hit / {overall:+.2f}% avg — the read shows edge so far.")
    elif hit < 45 or overall < 0:
        L.append(f"  VERDICT: {hit:.0f}% hit / {overall:+.2f}% avg — NO edge. Do not trade it.")
    else:
        L.append(f"  VERDICT: {hit:.0f}% hit / {overall:+.2f}% avg — inconclusive, keep collecting.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon", type=int, default=5, help="forward window in days")
    ap.add_argument("--telegram", action="store_true", help="DM the result")
    args = ap.parse_args()

    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    def tab(name):
        v = ss.worksheet(name).get_all_values()
        if not v:
            return []
        hdr = v[0]
        return [{hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))}
                for r in v[1:] if any(r)]

    alerts = tab("uoa_alerts")
    prices = build_price_index(tab("scan_results"))
    report = render(grade(alerts, prices, args.horizon), args.horizon, len(alerts))
    print(report)

    if args.telegram:
        from src import telegram as tg
        try:
            tg.send(report[:3900], chat_id=tg.PERSONAL_CHAT_ID)
            print("\n[telegram] sent to DM")
        except Exception as e:
            print(f"\n[telegram] send failed: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
