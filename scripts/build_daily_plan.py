#!/usr/bin/env python3
"""
build_daily_plan.py — THE single source of truth for what the auto-trader does.

One artifact, one pipeline. This aggregates the day's recommendations into the
`daily_plan` tab, which the PWA shows verbatim ("Today's Plan") and the Alpaca
executor trades verbatim. So you can watch the recommendation and trust the fill
matches it — no more "it traded something it never recommended".

The plan has two parts (the all-rounded book you asked for):
  • STANDING ALLOCATION — the hedge + protector sleeves, held continuously at
    target % of NLV (from config/risk_parity_targets.yaml): VIXM (vol hedge),
    IEF + TLT (Treasury ballast), GLD (gold protector).
  • OPPORTUNITIES — the top growth + option-income picks for today, ranked by
    conviction (a mix, capped small), from screen_candidates + scan_results.

Sizing mirrors Caspar's real account NLV (snapshot_caspar), same base the
executor already uses, so the paper book is a faithful proportional mirror.

Usage:
  python scripts/build_daily_plan.py --dry
  python scripts/build_daily_plan.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Standing allocation — the HELD base of a growth-tilted, all-rounded book
# (core-satellite). Held continuously, rebalanced to target, NOT daily picks:
#   • CORE growth (QQQ 45%) — the diversified equity engine (Caspar's ~64%
#     equity target, minus the satellite that the opportunities add on top).
#   • HEDGE (VIXM 5%) — convex tail hedge.
#   • PROTECTOR (IEF 6% + GLD 4%) — recession bond ballast + gold. TLT dropped:
#     long Treasuries are a duration/rate bet, not crash protection.
# Defensive total = 15% (lighter than the 23% risk-parity weight) because every
# defensive dollar drags CAGR and this book is deliberately growth-tilted.
STANDING_ALLOCATION = [
    {"ticker": "QQQ",  "leg": "core",      "pct": 45.0,
     "reason": "broad growth core (Nasdaq-100) — the diversified equity engine"},
    {"ticker": "VIXM", "leg": "hedge",     "pct": 5.0,
     "reason": "long-vol tail hedge — convex crisis ballast"},
    {"ticker": "IEF",  "leg": "protector", "pct": 6.0,
     "reason": "intermediate Treasuries — the justified recession ballast"},
    {"ticker": "GLD",  "leg": "protector", "pct": 4.0,
     "reason": "gold — uncorrelated inflation / crisis protector"},
]

INCOME_STRATEGIES = ("CSP", "CC", "PCS", "CCS", "IC", "LONG_CALL")
TOP_GROWTH = 5         # momentum satellite names in the plan (incl the AMD tier)
TOP_INCOME = 2         # option-income opportunities in the plan
SATELLITE_PER_NAME_PCT = 0.05   # each momentum satellite ~5% NLV → ~25% across 5


def _f(v, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return default


def standing_allocation_rows(nlv: float) -> list[dict]:
    """Hedge + protector sleeves sized to target % of NLV."""
    out = []
    for a in STANDING_ALLOCATION:
        notional = round(a["pct"] / 100.0 * nlv, 2)
        out.append({
            "leg": a["leg"], "ticker": a["ticker"], "strategy": "ALLOC",
            "detail": f"{a['pct']:.0f}% NLV → ${notional:,.0f}",
            "conviction": 100.0, "target_pct": a["pct"], "notional": notional,
            "reason": a["reason"], "source": "risk_parity",
        })
    return out


def _income_candidates(scan_rows: list[dict], today: str) -> list[dict]:
    """Best option-income pick per strategy for `today` (by composite_score)."""
    todays = [r for r in scan_rows if (r.get("date") or "")[:10] == today]
    best: dict[str, dict] = {}
    for r in todays:
        strat = "CSP" if (r.get("strategy") == "HARVEST_CSP") else str(r.get("strategy", ""))
        if strat not in INCOME_STRATEGIES:
            continue
        score = _f(r.get("composite_score"))
        if strat not in best or score > _f(best[strat].get("composite_score")):
            best[strat] = r
    rows = []
    for strat, r in best.items():
        prem = _f(r.get("premium"))
        strike = r.get("strike", "")
        dte = r.get("dte", "")
        rows.append({
            "leg": "income", "ticker": r.get("ticker", ""), "strategy": strat,
            "detail": f"{strat} {strike} @{prem:.2f}cr {dte}d",
            "conviction": _f(r.get("composite_score")), "target_pct": 0.0,
            "notional": 0.0,
            "reason": (r.get("notes") or "option-income pick")[:90],
            "source": "scan_results",
        })
    rows.sort(key=lambda x: x["conviction"], reverse=True)
    return rows


def _growth_candidates(screen_rows: list[dict], today: str, nlv: float,
                       per_name_pct: float = SATELLITE_PER_NAME_PCT) -> list[dict]:
    """Top momentum growth picks for `today` from screen_candidates."""
    todays = [r for r in screen_rows
              if (r.get("date") or "")[:10] == today
              and (r.get("source") or "").lower() == "momentum"]
    # de-dup by ticker (screen_candidates can carry dup rows), keep best score
    best: dict[str, dict] = {}
    for r in todays:
        tk = (r.get("ticker") or "").upper()
        if not tk:
            continue
        if tk not in best or _f(r.get("score")) > _f(best[tk].get("score")):
            best[tk] = r
    notional = round(per_name_pct * nlv, 2)
    rows = []
    for r in best.values():
        rows.append({
            "leg": "growth", "ticker": (r.get("ticker") or "").upper(),
            "strategy": "GROWTH",
            "detail": f"${notional:,.0f} notional",
            "conviction": _f(r.get("score")), "target_pct": 0.0,
            "notional": notional,
            "reason": (r.get("rationale") or "momentum")[:90],
            "source": "screen_candidates",
        })
    rows.sort(key=lambda x: x["conviction"], reverse=True)
    return rows


# Macro-lean tilt — regime-aware SIZING of the growth satellite (news as INPUT,
# never a trade signal). Hawkish/risk-off → don't add aggressively into a tape
# that compresses growth multiples; dovish/risk-on → lean in. Modest by design:
# it sizes the daily satellite, it does NOT touch the held core/hedge/protector.
_LEAN_TILT = {
    "hawkish":  (3, 0.03),   # (growth names, % NLV each) — trim adds
    "risk_off": (3, 0.03),
    "dovish":   (5, 0.06),   # lean in
    "risk_on":  (5, 0.06),
}


def build_plan(nlv: float, scan_rows: list[dict], screen_rows: list[dict],
               today: str, lean: str = "neutral") -> list[dict]:
    """Assemble the full ranked plan: standing allocation + top opportunities,
    with the growth satellite sized by today's macro-surprise `lean`."""
    plan = standing_allocation_rows(nlv)
    n_growth, sat_pct = _LEAN_TILT.get(lean, (TOP_GROWTH, SATELLITE_PER_NAME_PCT))
    income = _income_candidates(scan_rows, today)[:TOP_INCOME]
    growth = _growth_candidates(screen_rows, today, nlv, per_name_pct=sat_pct)[:n_growth]
    if lean in _LEAN_TILT:
        tilt = "trimmed (hawkish/risk-off)" if n_growth < TOP_GROWTH else "leaned-in (dovish/risk-on)"
        for g in growth:
            g["reason"] = f"[macro {lean}: {tilt}] {g['reason']}"[:90]
    opportunities = sorted(income + growth, key=lambda x: x["conviction"], reverse=True)
    plan.extend(opportunities)
    for i, row in enumerate(plan, start=1):
        row["rank"] = i
        row["execute"] = True            # everything in the plan is meant to trade
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print only, no sheet write")
    args = ap.parse_args()

    from src.sync import load_env
    from src import sheets as sh, schema as S
    load_env()

    client = sh.authenticate()
    ss = sh._open_sheet(client)

    def latest(tab):
        try:
            rows = ss.worksheet(tab).get_all_values()
            return [dict(zip(rows[0], r)) for r in rows[1:] if any(r)] if len(rows) > 1 else []
        except Exception:
            return []

    today = date.today().isoformat()
    nlv = 0.0
    try:
        nlv = _f(latest("snapshot_caspar")[-1].get("net_liq_usd"))
    except (IndexError, KeyError):
        pass
    if nlv <= 0:
        nlv = 8000.0   # safe fallback so the plan still renders

    # Today's macro-surprise lean (written by trigger_alerts) tilts growth sizing.
    lean = "neutral"
    try:
        ml = [r for r in latest("macro_lean") if (r.get("date") or "")[:10] == today]
        if ml:
            lean = (ml[-1].get("net_lean") or "neutral").lower()
    except (IndexError, KeyError):
        pass

    plan = build_plan(nlv, latest("scan_results"), latest("screen_candidates"), today, lean=lean)
    now_iso = S.now_sgt_iso()
    print(f"=== Daily Plan · {today} · NLV ${nlv:,.0f} · macro lean: {lean} · {len(plan)} rows ===\n")
    rows = []
    for p in plan:
        flag = "▶" if p["execute"] else " "
        print(f"  {flag} #{p['rank']:<2} {p['leg']:9} {p['ticker']:6} {p['strategy']:9} "
              f"conv {p['conviction']:5.1f}  {p['detail']}")
        rows.append(S.DailyPlanRow(
            date=today, rank=p["rank"], leg=p["leg"], ticker=p["ticker"],
            strategy=p["strategy"], detail=p["detail"], conviction=p["conviction"],
            target_pct=p["target_pct"], notional=p["notional"], reason=p["reason"],
            source=p["source"], execute=p["execute"], fill_status="", updated_at=now_iso))

    if args.dry or not rows:
        print(f"\n[{'DRY' if args.dry else 'NO-OP'}] {len(rows)} plan rows.")
        return 0

    sh.ensure_headers(client, S.DailyPlanRow.TAB_NAME, S.DailyPlanRow.HEADERS)
    ws = ss.worksheet(S.DailyPlanRow.TAB_NAME)
    existing = ws.get_all_values()
    keep = [existing[0]] if existing else [S.DailyPlanRow.HEADERS]
    keep += [r for r in (existing[1:] if existing else []) if r and r[0][:10] != today]
    keep += [r.to_row() for r in rows]
    ws.clear()
    ws.update("A1", keep, value_input_option="USER_ENTERED")
    print(f"\n✓ Wrote {len(rows)} rows to daily_plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
