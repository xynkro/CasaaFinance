#!/usr/bin/env python3
"""
Crash playbook — decide the response BEFORE the drawdown, not during it.

Two jobs, both answering "do we actually have a plan?":

  1. HEDGE DRIFT — is the protective sleeve actually on, at the weight the plan
     says? (The 2026-08-24 check found VIXM, the only convex crash hedge, at
     1.6% of book against a 5% target — a third of plan.)
  2. DRAWDOWN TIER — where is SPX versus its trailing high, and what did you
     pre-commit to do at that tier?

The tier ACTIONS below are pre-commitments YOU set while calm; the script only
reports which one is live and whether the book matches it. It never places an
order and never invents a target. Edit TIERS / HEDGE_TARGETS to change policy.

Why pre-commit: this repo's own graded history is unambiguous about improvising
direction — 1 right / 9 wrong / 8 noise across every alert ever sent, and a
composite score that ranks its best ideas worst. Rules written in advance are
the part that has actually worked (the 50% / 2x / 21-DTE exits).

USAGE
  python scripts/crash_playbook.py              # print the playbook
  python scripts/crash_playbook.py --telegram   # also DM it (never the group)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sheets as sh  # noqa: E402
from src.sync import load_env  # noqa: E402

# Protective sleeve targets as % of book. Proxies are treated as satisfying the
# same slot (GLDM is gold; TLT is long duration alongside IEF).
HEDGE_TARGETS = {
    "VIXM": {"target_pct": 5.0, "proxies": [], "role": "convex long-vol tail hedge"},
    "IEF":  {"target_pct": 6.0, "proxies": ["TLT"], "role": "duration / recession ballast"},
    "GLD":  {"target_pct": 4.0, "proxies": ["GLDM"], "role": "uncorrelated crisis protector"},
}

# Drawdown tiers, worst-first. `floor_pct` is SPX drawdown from trailing high.
TIERS = [
    {"name": "BEAR",       "floor_pct": -20.0,
     "action": "Hedges have done their job — harvest them. Rebuild core in tranches, "
               "not all at once. This is the tier where dry powder matters most."},
    {"name": "CORRECTION", "floor_pct": -10.0,
     "action": "Stop opening new risk. Verify hedge sleeve is at FULL target. "
               "Begin staged deployment of reserve cash only per pre-set tranches."},
    {"name": "PULLBACK",   "floor_pct": -5.0,
     "action": "No new leverage, no new short premium into weakness. Top the hedge "
               "sleeve back up to target if it has drifted."},
    {"name": "NORMAL",     "floor_pct": -1e9,
     "action": "Routine. Keep the hedge sleeve at target and keep a cash reserve — "
               "the cheapest time to buy insurance is when nobody wants it."},
]

# Below this, the account has no meaningful ability to act in a drawdown.
DRY_POWDER_FLOOR_PCT = 5.0


def _f(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def drawdown_pct(spx_series: list[float]) -> float:
    """Current SPX drawdown % from the trailing high of the supplied series."""
    vals = [v for v in spx_series if v and v > 0]
    if not vals:
        return 0.0
    peak = max(vals)
    return (vals[-1] / peak - 1) * 100 if peak else 0.0


def tier_for(dd_pct: float, tiers: list[dict] | None = None) -> dict:
    """The pre-committed tier whose floor the drawdown has breached."""
    for t in (tiers or TIERS):
        if dd_pct <= t["floor_pct"]:
            return t
    return (tiers or TIERS)[-1]


def hedge_drift(held: dict[str, float], total: float,
                targets: dict | None = None) -> list[dict]:
    """Per-slot actual vs target weight, counting proxies toward the slot."""
    targets = targets or HEDGE_TARGETS
    out = []
    for slot, cfg in targets.items():
        names = [slot] + list(cfg.get("proxies") or [])
        have = sum(held.get(n, 0.0) for n in names)
        pct = (have / total * 100) if total else 0.0
        tgt = cfg["target_pct"]
        out.append({
            "slot": slot, "role": cfg["role"], "via": [n for n in names if held.get(n)],
            "have_usd": have, "have_pct": pct, "target_pct": tgt,
            "gap_pct": pct - tgt,
            "status": "OK" if pct >= tgt * 0.8 else ("LIGHT" if pct > 0 else "ABSENT"),
        })
    return out


def render(dd, tier, drifts, nlv, cash, total) -> str:
    L = ["CRASH PLAYBOOK — the plan, decided in advance", ""]
    cash_pct = (cash / nlv * 100) if nlv else 0.0
    L.append(f"SPX drawdown from trailing high: {dd:+.1f}%   →   TIER: {tier['name']}")
    L.append(f"  pre-committed action: {tier['action']}")
    L.append("")
    L.append("HEDGE SLEEVE — is the protection actually on?")
    L.append(f"  {'slot':7}{'have':>9}{'target':>9}{'gap':>9}  status   role")
    for d in drifts:
        via = f" (via {'+'.join(d['via'])})" if d["via"] and d["slot"] not in d["via"] else ""
        L.append(f"  {d['slot']:7}{d['have_pct']:>8.1f}%{d['target_pct']:>8.1f}%"
                 f"{d['gap_pct']:>+8.1f}%  {d['status']:8} {d['role']}{via}")
    worst = [d for d in drifts if d["status"] != "OK"]
    if worst:
        L.append(f"  ⚠ {len(worst)} slot(s) below plan: "
                 + ", ".join(f"{d['slot']} {d['have_pct']:.1f}%/{d['target_pct']:.0f}%" for d in worst))
    L.append("")
    L.append("DRY POWDER — the ability to act at all")
    L.append(f"  cash ${cash:,.0f} of ${nlv:,.0f} NLV = {cash_pct:.1f}%")
    if cash_pct < DRY_POWDER_FLOOR_PCT:
        L.append(f"  ⚠ below the {DRY_POWDER_FLOOR_PCT:.0f}% floor — a drawdown would be taken in full "
                 "with nothing available to deploy into it.")
    L.append("")
    L.append("Note: tier actions are YOUR pre-commitments (edit TIERS in this file).")
    L.append("This script reports state and never places an order.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--telegram", action="store_true", help="DM the playbook (never the group)")
    ap.add_argument("--account", default="caspar")
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

    macro = tab("macro")
    spx = [_f(r.get("spx")) for r in macro]
    dd = drawdown_pct([v for v in spx if v is not None][-260:])
    tier = tier_for(dd)

    pos = tab(f"positions_{args.account}")
    last = max(((r.get("date") or "")[:10] for r in pos), default="")
    today_pos = [r for r in pos if (r.get("date") or "")[:10] == last]
    held: dict[str, float] = {}
    for r in today_pos:
        mv = _f(r.get("mkt_val")) or 0.0
        held[(r.get("ticker") or "").upper()] = held.get((r.get("ticker") or "").upper(), 0.0) + mv
    total = sum(held.values())

    snaps = tab(f"snapshot_{args.account}")
    snap = max(snaps, key=lambda r: r.get("date", "")) if snaps else {}
    nlv = _f(snap.get("net_liq_usd")) or _f(snap.get("net_liq_sgd")) or total
    cash = _f(snap.get("cash")) or _f(snap.get("cash_sgd")) or 0.0

    report = render(dd, tier, hedge_drift(held, total), nlv, cash, total)
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
