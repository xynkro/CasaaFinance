#!/usr/bin/env python3
"""
alpaca_paper_execute.py — Auto-execute the CasaaFinance scanner's picks on the
Alpaca PAPER account, to build a real-fill forward track record of the system's
recommendations (closes the audit's "can't measure our own edge" gap).

Policy (confirmed 2026-05-30):
  • Selection : the single highest-composite pick PER STRATEGY, for today.
  • Sizing    : mirror Caspar's real account — Tranche-1b "aggressive" profile
                (recommended contract count; skip a pick the system sizes to 0).
  • Orders    : LIMIT at the pick's premium/credit. Single-leg for CSP/CC/
                LONG_CALL, multi-leg (mleg) for PCS/CCS/IC. PMCC skipped for now
                (diagonal needs two expiries the notes don't cleanly carry).
  • Safety    : PAPER ONLY (hard-guarded on the base URL). Dry-run by default;
                --execute places. Idempotent via deterministic client_order_id.

Usage:
  python scripts/alpaca_paper_execute.py            # dry-run: print the plan
  python scripts/alpaca_paper_execute.py --execute  # place on Alpaca PAPER
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Strategies we can map to Alpaca orders today.
SINGLE_LEG = {"CSP": ("P", "sell_to_open"), "CC": ("C", "sell_to_open"),
              "LONG_CALL": ("C", "buy_to_open")}
SPREAD = {"PCS", "CCS", "IC"}
UNSUPPORTED = {"PMCC", "LONG_PUT"}
# Short-premium (credit) strategies gated by the GEX regime: skip NEW entries on
# negative-gamma (SELL_CAUTION) days when gap risk runs through the short strikes.
PREMIUM_SELLING = {"CSP", "CC", "PCS", "CCS", "IC"}


# ──────────────────── Pure helpers (unit-tested) ────────────────────────────

def _f(x, d: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def norm_expiry(e: str) -> str:
    """'YYYYMMDD' or 'YYYY-MM-DD' → 'YYYY-MM-DD'."""
    e = str(e).replace("-", "")
    return f"{e[:4]}-{e[4:6]}-{e[6:8]}" if len(e) == 8 else str(e)


def parse_leg_strikes(notes: str) -> dict[str, float]:
    """Extract leg strikes from a scanner notes string, e.g.
    'SP:95/LP:90/SC:110/LC:115 W:$5' → {'SP':95,'LP':90,'SC':110,'LC':115}.
    Ignores any appended ' | size C:1x ...' sizing tag."""
    out: dict[str, float] = {}
    for tag, val in re.findall(r"\b(SP|LP|SC|LC):(\d+(?:\.\d+)?)", notes or ""):
        out[tag] = float(val)
    return out


def select_top_per_strategy(picks: list[dict], today: str) -> list[dict]:
    """Highest composite_score pick per strategy for `today` (HARVEST_CSP folds
    into CSP). Returns at most one pick per canonical strategy."""
    best: dict[str, dict] = {}
    today = today[:10]
    for p in picks:
        # scan_results dates carry an audit timestamp suffix ("2026-05-30T103045"
        # or "... HH:MM:SS"); the date is always the first 10 chars.
        if str(p.get("date", ""))[:10] != today:
            continue
        strat = "CSP" if (p.get("strategy") == "HARVEST_CSP") else str(p.get("strategy", ""))
        if not strat:
            continue
        score = _f(p.get("composite_score"))
        if strat not in best or score > _f(best[strat].get("composite_score")):
            best[strat] = p
    return list(best.values())


def pick_to_order(pick: dict) -> tuple[dict | None, str]:
    """Map a scan_results pick → an Alpaca order spec, or (None, reason).

    Spec (single): {kind:'single', occ, side, limit_price, label}
    Spec (mleg):   {kind:'mleg', legs:[{symbol,position_intent}], limit_price, label}
    """
    from src import alpaca
    strat = (pick.get("strategy") or "").upper()
    if strat == "HARVEST_CSP":
        strat = "CSP"
    tk = str(pick.get("ticker", "")).upper()
    expiry = norm_expiry(pick.get("expiry", ""))
    prem = round(_f(pick.get("premium")), 2)
    if not tk or len(expiry) != 10:
        return None, "missing ticker/expiry"
    if strat in UNSUPPORTED:
        return None, f"{strat} mapping not yet supported"

    if strat in SINGLE_LEG:
        right, intent = SINGLE_LEG[strat]
        strike = _f(pick.get("strike"))
        if strike <= 0:
            return None, "bad strike"
        occ = alpaca.occ_symbol(tk, expiry, right, strike)
        side = "buy" if intent.startswith("buy") else "sell"
        return {"kind": "single", "occ": occ, "side": side, "limit_price": prem,
                "label": f"{strat} {tk} {strike:.0f}{right} @{prem}"}, ""

    if strat in SPREAD:
        s = parse_leg_strikes(pick.get("notes", ""))
        need = {"PCS": ("SP", "LP"), "CCS": ("SC", "LC"),
                "IC": ("SP", "LP", "SC", "LC")}[strat]
        if not all(k in s for k in need):
            return None, f"{strat} legs unparseable from notes"
        leg_map = {
            "SP": ("P", "sell_to_open"), "LP": ("P", "buy_to_open"),
            "SC": ("C", "sell_to_open"), "LC": ("C", "buy_to_open"),
        }
        legs = []
        for k in need:
            right, intent = leg_map[k]
            legs.append({"symbol": alpaca.occ_symbol(tk, expiry, right, s[k]),
                         "position_intent": intent})
        return {"kind": "mleg", "legs": legs, "limit_price": prem,
                "label": f"{strat} {tk} {'/'.join(f'{k}{s[k]:.0f}' for k in need)} @{prem}cr"}, ""

    return None, f"unknown strategy {strat}"


def client_order_id(today: str, pick: dict) -> str:
    """Deterministic id so re-runs don't double-place. <=48 chars."""
    strat = "CSP" if pick.get("strategy") == "HARVEST_CSP" else str(pick.get("strategy", ""))
    return f"casaa-{today}-{strat}-{str(pick.get('ticker',''))}"[:48]


# ──────────────────── Sizing (mirror Caspar / Tranche 1b) ───────────────────

_DEFINED_OR_DEBIT = {"PCS", "CCS", "IC", "PMCC", "LONG_CALL", "LONG_PUT"}


def contracts_for(pick: dict, nlv: float, excess_liq: float | None,
                  vix: float, spx_above_200dma: bool) -> int:
    """Recommended contract count under Caspar's aggressive profile (Tranche 1b)."""
    from src.position_sizing import size_candidate
    strat = "CSP" if pick.get("strategy") == "HARVEST_CSP" else (pick.get("strategy") or "")
    override = _f(pick.get("cash_required")) if strat.upper() in _DEFINED_OR_DEBIT else None
    sr = size_candidate(
        strategy=strat, strike=_f(pick.get("strike")),
        underlying=_f(pick.get("underlying_last")), premium=_f(pick.get("premium")),
        profile_name="aggressive", nlv=nlv, excess_liquidity=excess_liq,
        is_margin=True, bpr_override=override, vix=vix, spx_above_200dma=spx_above_200dma)
    return sr.recommended_contracts


# ──────────────────── I/O + main ────────────────────────────────────────────

# ──────────────────── Growth stock picks (momentum + confluence) ────────────

GROWTH_PER_NAME_PCT = 0.10   # cap each growth stock at 10% of (mirrored) NLV
GROWTH_TOP_N = 5             # momentum names to buy per run


def select_growth_picks(rows: list[dict], today: str, top_n: int = GROWTH_TOP_N) -> list[dict]:
    """Top momentum stock candidates for `today` from screen_candidates
    (source='momentum' — written by growth_scan, confluence-adjusted)."""
    today = today[:10]
    cands = [r for r in rows
             if str(r.get("source", "")).lower() == "momentum"
             and str(r.get("date", ""))[:10] == today]
    cands.sort(key=lambda r: _f(r.get("score")), reverse=True)
    return cands[:top_n]


def stock_order_spec(pick: dict, nlv: float) -> tuple[dict | None, str]:
    """Map a momentum screen_candidate → an Alpaca equity BUY spec (NOTIONAL /
    fractional, so no name is priced out of a small account), or (None, reason)."""
    tk = str(pick.get("ticker", "")).upper()
    price = _f(pick.get("trigger_price"))
    if not tk:
        return None, "missing ticker"
    if nlv <= 0:
        return None, "no NLV"
    notional = round(GROWTH_PER_NAME_PCT * nlv, 2)
    if notional < 1:
        return None, "budget < $1"
    approx = (notional / price) if price > 0 else 0.0
    return {"kind": "equity", "symbol": tk, "side": "buy", "notional": notional,
            "label": f"BUY {tk} ${notional:.0f} (~{approx:.2f}sh @{price:.2f})"}, ""


def _read_picks_and_account():
    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    def latest(tab):
        try:
            rows = ss.worksheet(tab).get_all_values()
            return [dict(zip(rows[0], r)) for r in rows[1:] if any(r)] if len(rows) > 1 else []
        except Exception:
            return []

    picks = latest("scan_results")
    growth = latest("screen_candidates")
    acct = {"nlv": 0.0, "excess_liq": None}
    try:
        c = latest("snapshot_caspar")[-1]
        acct["nlv"] = _f(c.get("net_liq_usd"))
        acct["excess_liq"] = _f(c.get("excess_liq")) or None
    except (IndexError, KeyError):
        pass
    macro = {}
    try:
        macro = latest("macro")[-1]
    except IndexError:
        pass
    # GEX premium-selling gate (SPY, today) — permissive default if absent.
    gex_gate = {"gate": "NORMAL", "note": ""}
    try:
        td = date.today().isoformat()
        spy = [r for r in latest("gex_regime")
               if (r.get("symbol") or "").upper() == "SPY"
               and (r.get("date") or "")[:10] == td]
        if spy:
            gex_gate = {"gate": spy[-1].get("premium_gate") or "NORMAL",
                        "note": spy[-1].get("note") or ""}
    except Exception:
        pass
    return picks, growth, acct, macro, gex_gate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Actually place orders on Alpaca PAPER (default: dry-run print only)")
    args = ap.parse_args()

    # HARD PAPER GUARD — refuse to place unless the base URL is the paper endpoint.
    # `or` (not get-default): CI sets ALPACA_BASE_URL to an unset secret's EMPTY
    # string → empty/missing must fail SAFE to the paper endpoint (the only
    # supported mode), not fail CLOSED and refuse. A real non-paper URL is still
    # refused below.
    base = os.environ.get("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
    if args.execute and "paper-api" not in base:
        print(f"REFUSING: ALPACA_BASE_URL is not paper-api ({base}). This tool is PAPER ONLY.")
        return 2

    today = date.today().isoformat()
    picks, growth, acct, macro, gexg = _read_picks_and_account()
    vix = _f(macro.get("vix"), 16.0)
    spx_ok = str(macro.get("spx_above_200sma", "True")).lower() not in ("false", "0", "")
    gex_caution = (gexg.get("gate") == "SELL_CAUTION")

    top = select_top_per_strategy(picks, today)
    growth_top = select_growth_picks(growth, today)
    print(f"=== Alpaca paper executor · {today} · NLV ${acct['nlv']:,.0f} "
          f"excess ${acct['excess_liq'] or 0:,.0f} · VIX {vix} ===")
    if gexg.get("note"):
        print(f"  GEX: {gexg['note']}")
    print(f"{len(top)} option picks + {len(growth_top)} growth stock picks for today\n")

    from src import alpaca
    plan = []
    # Options (top per strategy)
    for p in top:
        strat = "CSP" if p.get("strategy") == "HARVEST_CSP" else (p.get("strategy") or "")
        if gex_caution and strat in PREMIUM_SELLING:
            print(f"  SKIP {strat:10} {str(p.get('ticker','')):6} — GEX SELL_CAUTION "
                  f"(SPY short gamma → gap risk through short strikes)")
            continue
        spec, reason = pick_to_order(p)
        if spec is None:
            print(f"  SKIP {p.get('strategy'):10} {p.get('ticker'):6} — {reason}")
            continue
        qty = contracts_for(p, acct["nlv"], acct["excess_liq"], vix, spx_ok)
        if qty <= 0:
            print(f"  SKIP {spec['label']} — sized to 0 contracts (Caspar profile)")
            continue
        coid = client_order_id(today, p)
        plan.append((spec, qty, coid))
        print(f"  PLAN {spec['label']}  ×{qty}  [{spec['kind']}]  id={coid}")

    # Growth stocks (momentum + confluence) — the offense leg, as paper equity buys
    for g in growth_top:
        spec, reason = stock_order_spec(g, acct["nlv"])
        if spec is None:
            print(f"  SKIP GROWTH    {str(g.get('ticker','')):6} — {reason}")
            continue
        coid = f"casaa-{today}-GROWTH-{str(g.get('ticker',''))}"[:48]
        plan.append((spec, 0, coid))   # qty unused for notional equity
        print(f"  PLAN {spec['label']}  [equity]  id={coid}")

    if not args.execute:
        print(f"\n[DRY-RUN] {len(plan)} orders planned. Re-run with --execute to place on PAPER.")
        return 0

    # Idempotency: skip ids already submitted (open or closed today).
    existing = {o.get("client_order_id") for o in alpaca.get_orders(status="all", limit=500)}
    placed = 0
    for spec, qty, coid in plan:
        if coid in existing:
            print(f"  ALREADY PLACED {coid} — skip")
            continue
        try:
            if spec["kind"] == "equity":
                alpaca.submit_notional_order(spec["symbol"], spec["notional"], "buy",
                                             client_order_id=coid)
            elif spec["kind"] == "single":
                alpaca.submit_option_order(spec["occ"], qty, spec["side"],
                                           limit_price=spec["limit_price"], client_order_id=coid)
            else:
                alpaca.submit_mleg_order(spec["legs"], qty=qty,
                                         limit_price=spec["limit_price"], client_order_id=coid)
            placed += 1
            print(f"  ✓ PLACED {spec['label']} ×{qty}")
        except Exception as e:
            print(f"  ✗ FAILED {spec['label']} — {e}")
    print(f"\nPlaced {placed}/{len(plan)} orders on Alpaca PAPER.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
