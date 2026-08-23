#!/usr/bin/env python3
"""
Policy audit — does the recommendation engine actually make money?

A repeatable version of the 2026-08-20 audit that produced the current scan
policy (see scripts/daily_options_scan.py: DISABLED_SPREAD_STRATS, ranking_key,
and scripts/trigger_alerts.py: cooldown_blocker). It re-answers three questions
against live data so the policy is re-checked rather than remembered:

  1. Per strategy — win rate and average forward return (is the wheel still the
     part that works, are spreads still the part that loses?).
  2. Is `composite_score` still anti-predictive (score quartile vs forward
     return + correlation)?
  3. Alert quality — of the pages actually sent, how many went our way? A move
     inside +/-BAND_PCT is graded NOISE, not a call, so tiny wiggles don't
     flatter or damn the record.

Every number is printed next to the 2026-08-20 BASELINE so drift is visible.
Read-only against the Sheet; the optional Telegram summary goes to the DM
(it names positions/strategies — never the shared group).

USAGE
  python scripts/policy_audit.py              # print the report
  python scripts/policy_audit.py --telegram   # also DM the summary
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sheets as sh  # noqa: E402
from src.sync import load_env  # noqa: E402

# Grading band: a move smaller than this is noise, not a right/wrong call.
BAND_PCT = 1.0

# Direction each alert wanted. Superset of trigger_alerts.BUY_STRATEGIES because
# the audit also grades scanner strategies that never page.
WANT_UP = {"BUY_DIP", "CSP", "PMCC", "LONG_CALL", "PCS", "HARVEST_CSP"}

SPREADS = {"PCS", "CCS", "IC"}

# 2026-08-20 baseline (n=2328 evaluations, 18 alerts) — what the policy was set on.
BASELINE_STRATEGY = {
    "CSP": (81, 1.4), "CC": (62, 2.8), "IC": (39, -3.6),
    "PCS": (36, -4.7), "CCS": (40, -3.5),
}
BASELINE_QUARTILE = (1.62, -1.77)   # (lowest-score avg fwd, highest-score avg fwd)
BASELINE_CORR = -0.089
BASELINE_ALERTS = (1, 9, 8)         # right, wrong, noise


def _f(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def pearson(pairs: list[tuple[float, float]]) -> float:
    """Pearson correlation of (x, y) pairs. 0.0 when undefined."""
    if len(pairs) < 2:
        return 0.0
    mx = st.mean(x for x, _ in pairs)
    my = st.mean(y for _, y in pairs)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den = (sum((x - mx) ** 2 for x, _ in pairs) * sum((y - my) ** 2 for _, y in pairs)) ** 0.5
    return (num / den) if den else 0.0


def dedupe(rows: list[dict]) -> list[dict]:
    """signal_outcomes carries repeat evaluations; keep one per logical trade."""
    seen, out = set(), []
    for r in rows:
        k = (r.get("scan_date"), r.get("eval_date"), r.get("ticker"),
             r.get("strategy"), r.get("strike"), r.get("expiry"))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def grade_by_strategy(rows: list[dict]) -> list[dict]:
    """Per-strategy win rate + forward return, most-evaluated first."""
    by = defaultdict(list)
    for r in rows:
        s = str(r.get("strategy") or "?").upper()
        by[s].append(r)
    out = []
    for s, g in by.items():
        fw = [v for v in (_f(r.get("fwd_return_pct")) for r in g) if v is not None]
        outs = [str(r.get("strategy_outcome") or "").upper() for r in g]
        graded = [o for o in outs if o]
        wins = sum(1 for o in graded if o == "WIN")
        out.append({
            "strategy": s, "n": len(g),
            "win_pct": (wins / len(graded) * 100) if graded else None,
            "avg_fwd": st.mean(fw) if fw else None,
            "med_fwd": st.median(fw) if fw else None,
        })
    return sorted(out, key=lambda d: -d["n"])


def score_quartiles(pairs: list[tuple[float, float]]) -> list[dict]:
    """(score, fwd_return) sorted by score, split into 4 equal buckets."""
    pairs = sorted(pairs)
    n = len(pairs)
    if n < 4:
        return []
    q = n // 4
    segs = [("Q1 (lowest score)", pairs[:q]), ("Q2", pairs[q:2 * q]),
            ("Q3", pairs[2 * q:3 * q]), ("Q4 (highest score)", pairs[3 * q:])]
    return [{
        "label": lbl, "n": len(seg),
        "avg_score": st.mean(a for a, _ in seg),
        "avg_fwd": st.mean(b for _, b in seg),
        "win_pct": sum(1 for _, b in seg if b > 0) / len(seg) * 100,
    } for lbl, seg in segs if seg]


def grade_alerts(alerts: list[dict], band_pct: float = BAND_PCT) -> dict:
    """Grade sent alerts by whether price moved the way the alert wanted.

    A move within +/-band_pct is NOISE. Returns counts plus the wrong ones.
    """
    right = wrong = noise = 0
    wrongs = []
    for a in alerts:
        e, cur = _f(a.get("entry_price")), _f(a.get("current_price"))
        if not e or cur is None or e == 0:
            continue
        mv = (cur / e - 1) * 100
        if abs(mv) < band_pct:
            noise += 1
            continue
        strat = str(a.get("strategy") or "").upper()
        if (mv > 0) == (strat in WANT_UP):
            right += 1
        else:
            wrong += 1
            wrongs.append({"ticker": a.get("ticker"), "strategy": strat,
                           "move_pct": mv, "at": (a.get("last_alert_at") or "")[:10]})
    return {"right": right, "wrong": wrong, "noise": noise,
            "wrongs": sorted(wrongs, key=lambda w: w["at"])}


def _arrow(now: float | None, base: float) -> str:
    if now is None:
        return ""
    d = now - base
    return f"  (baseline {base:+.1f}, {d:+.1f})" if abs(d) >= 0.05 else f"  (baseline {base:+.1f}, flat)"


def render_report(strat_rows, quarts, corr, alerts, window) -> str:
    L = []
    L.append("POLICY AUDIT — is the recommendation engine making money?")
    L.append(f"window: {window}")
    L.append("")
    L.append("1. BY STRATEGY (baseline = 2026-08-20, the audit the policy was set on)")
    L.append(f"   {'strategy':12}{'n':>6}{'win%':>8}{'avg fwd%':>11}   vs baseline")
    for r in strat_rows:
        b = BASELINE_STRATEGY.get(r["strategy"])
        note = ""
        if b:
            note = f"was {b[0]}% / {b[1]:+.1f}%"
            if r["avg_fwd"] is not None:
                note += f" → {r['avg_fwd']:+.1f}%"
        tag = "  ⛔ DISABLED" if r["strategy"] in SPREADS else ""
        w = f"{r['win_pct']:.0f}%" if r["win_pct"] is not None else "-"
        a = f"{r['avg_fwd']:.1f}" if r["avg_fwd"] is not None else "-"
        L.append(f"   {r['strategy']:12}{r['n']:>6}{w:>8}{a:>11}   {note}{tag}")
    L.append("")
    L.append("2. IS composite_score STILL ANTI-PREDICTIVE?")
    L.append(f"   {'quartile':22}{'n':>6}{'avg score':>11}{'avg fwd%':>10}{'win%':>8}")
    for q in quarts:
        L.append(f"   {q['label']:22}{q['n']:>6}{q['avg_score']:>11.1f}"
                 f"{q['avg_fwd']:>10.2f}{q['win_pct']:>7.0f}%")
    if quarts:
        spread = quarts[-1]["avg_fwd"] - quarts[0]["avg_fwd"]
        L.append(f"   correlation(score, fwd) = {corr:+.3f}   (baseline {BASELINE_CORR:+.3f})")
        L.append(f"   high-minus-low = {spread:+.2f} pts "
                 f"(baseline {BASELINE_QUARTILE[1] - BASELINE_QUARTILE[0]:+.2f}) — "
                 f"{'still INVERTED, keep ranking off it' if spread < 0 else 'no longer inverted — worth re-testing as a ranker'}")
    L.append("")
    br, bw, bn = BASELINE_ALERTS
    L.append("3. ALERT QUALITY (moves within ±%.1f%% graded as noise)" % BAND_PCT)
    L.append(f"   right {alerts['right']}  |  wrong {alerts['wrong']}  |  noise {alerts['noise']}"
             f"     (baseline {br} / {bw} / {bn})")
    if alerts["wrongs"]:
        L.append("   pages that went the wrong way:")
        for w in alerts["wrongs"][:10]:
            L.append(f"     {w['at']}  {str(w['ticker']):6} {w['strategy']:9} {w['move_pct']:+6.1f}% against")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--telegram", action="store_true",
                    help="DM the summary (personal chat only — never the group)")
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

    rows = dedupe(tab("signal_outcomes"))
    if not rows:
        print("signal_outcomes is empty — nothing to audit.")
        return 1
    window = (f"{min(r.get('scan_date','') for r in rows)} → "
              f"{max(r.get('eval_date','') for r in rows)}  ({len(rows)} evaluations)")

    strat_rows = grade_by_strategy(rows)
    pairs = [(_f(r.get("scan_composite")), _f(r.get("fwd_return_pct"))) for r in rows]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    quarts = score_quartiles(pairs)
    corr = pearson(pairs)

    sent = [a for a in tab("trigger_alerts") if (a.get("last_alert_at") or "").strip()]
    alerts = grade_alerts(sent)

    report = render_report(strat_rows, quarts, corr, alerts, window)
    print(report)

    if args.telegram:
        from src import telegram as tg
        try:
            tg.send(report[:3900], chat_id=tg.PERSONAL_CHAT_ID)
            print("\n[telegram] summary sent to DM")
        except Exception as e:
            print(f"\n[telegram] send failed: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
