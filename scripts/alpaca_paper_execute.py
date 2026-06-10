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
from datetime import date, datetime, timedelta
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


def parse_audit_ts(s: str) -> datetime | None:
    """Sheet audit timestamp → datetime ('YYYY-MM-DDTHHMMSS' _ts_suffix
    convention, 'YYYY-MM-DD HH:MM:SS', ISO with colons, or bare date)."""
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%dT%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def latest_by_parsed_ts(rows: list[dict], date_key: str = "date") -> dict | None:
    """Latest row by PARSED timestamp — NOT rows[-1]. Audit tabs (macro,
    gex_regime, ...) are append-UNORDERED: Mac + cloud writers interleave, so
    e.g. the macro tab's 2026-06-09T180409 row physically precedes T005009.
    Ties go to the later physical row (the fresher write)."""
    best, best_ts = None, None
    for d in rows:
        ts = parse_audit_ts(d.get(date_key, ""))
        if ts is None:
            continue
        if best_ts is None or ts >= best_ts:
            best, best_ts = d, ts
    return best


MACRO_TAB_MAX_AGE_HOURS = 72.0   # weekend-tolerant freshness window for macro rows


def merge_macro_rows(rows: list[dict], now: datetime | None = None,
                     max_age_hours: float = MACRO_TAB_MAX_AGE_HOURS) -> dict:
    """Field-level merge of macro-tab rows: NEWEST non-blank value per field by
    PARSED timestamp, ignoring rows older than `max_age_hours`.

    Why not the single latest row: the macro tab has MULTIPLE writers
    (macro_grab, daily_tracker, sync sidecar) and only macro_grab fills
    spx_above_200sma — a tracker row landing last would mask the flag and
    permanently degrade sizing. Never invents values: fields absent from every
    fresh row stay absent, and macro_sizing_context degrades fail-safe."""
    now = now or datetime.now()
    cutoff = now - timedelta(hours=max_age_hours)
    fresh = []
    for i, d in enumerate(rows):
        ts = parse_audit_ts(d.get("date", ""))
        if ts is not None and ts >= cutoff:
            fresh.append((ts, i, d))
    if not fresh:
        return {}
    fresh.sort(key=lambda t: (t[0], t[1]), reverse=True)   # newest first; ties → later physical
    out: dict = {"asof": fresh[0][2].get("date", "")}
    for _, _, row in fresh:
        for key in ("vix", "spx_above_200sma"):
            if key not in out and str(row.get(key) or "").strip():
                out[key] = str(row.get(key)).strip()
    return out


def macro_sizing_context(macro: dict) -> tuple[float, bool, bool]:
    """(vix, spx_above_200sma, degraded) from the merged macro-tab values.

    FAIL-SAFE: the old code defaulted VIX→16.0 and spx_above_200sma→True when
    the columns were missing (the spx_above_200sma column didn't even exist),
    so a dead feed sized at FULL regime multiplier. Now: VIX missing/unparseable
    OR SPX-vs-200dma unknown → degraded=True, and the caller applies a 0.5
    multiplier (CAUTION-equivalent) on top of whatever IS known. A known-bad
    state (VIX>30 / SPX below) still halts via regime_multiplier as before."""
    vix = _f(macro.get("vix"), 0.0)
    vix_known = vix > 0
    sa = str(macro.get("spx_above_200sma") if macro.get("spx_above_200sma") is not None else "").strip().lower()
    spx_known = sa in ("true", "false", "1", "0")
    # True here is only the *sizing input* when the state is known; when unknown
    # the degraded 0.5 multiplier covers it (never full-size on missing data).
    spx_ok = sa in ("true", "1") if spx_known else True
    degraded = not (vix_known and spx_known)
    return vix, spx_ok, degraded


def income_skip_reason(strat: str, gex_caution: bool, blackout_event: dict | None) -> str | None:
    """Pre-placement gates for NEW premium-selling legs (None = proceed).
    Mirrors: GEX SELL_CAUTION skip + macro event blackout (high-impact US event
    inside 48h → don't open fresh short premium into FOMC/CPI/NFP)."""
    if strat in PREMIUM_SELLING:
        if gex_caution:
            return "skipped:GEX SELL_CAUTION"
        if blackout_event:
            return "skipped:EVENT_BLACKOUT"
    return None


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
                  vix: float, spx_above_200dma: bool, degraded: bool = False) -> int:
    """Recommended contract count under Caspar's aggressive profile (Tranche 1b).
    degraded=True (VIX / SPX-200dma unknowable from the macro tab) applies a
    0.5 CAUTION-equivalent multiplier — never full-size on missing data."""
    from src.position_sizing import size_candidate
    strat = "CSP" if pick.get("strategy") == "HARVEST_CSP" else (pick.get("strategy") or "")
    override = _f(pick.get("cash_required")) if strat.upper() in _DEFINED_OR_DEBIT else None
    sr = size_candidate(
        strategy=strat, strike=_f(pick.get("strike")),
        underlying=_f(pick.get("underlying_last")), premium=_f(pick.get("premium")),
        profile_name="aggressive", nlv=nlv, excess_liquidity=excess_liq,
        is_margin=True, bpr_override=override, vix=vix, spx_above_200dma=spx_above_200dma)
    n = sr.recommended_contracts
    if degraded and n > 0:
        n = int(n * 0.5)
    return n


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


def _norm_strat(s: str) -> str:
    return "CSP" if s == "HARVEST_CSP" else str(s or "")


def _read_plan_and_context():
    """Read the ONE source of truth (daily_plan) plus what's needed to execute
    it: scan_results (to rebuild option-spread legs), account NLV, VIX, GEX gate,
    and current positions (to rebalance standing allocation to target, not re-buy)."""
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

    td = date.today().isoformat()
    plan = [r for r in latest("daily_plan")
            if (r.get("date") or "")[:10] == td
            and str(r.get("execute", "")).upper() in ("TRUE", "1", "YES")]
    scan = latest("scan_results")
    acct = {"nlv": 0.0, "excess_liq": None}
    try:
        c = latest("snapshot_caspar")[-1]
        acct["nlv"] = _f(c.get("net_liq_usd"))
        acct["excess_liq"] = _f(c.get("excess_liq")) or None
    except (IndexError, KeyError):
        pass
    # Macro values by PARSED timestamp, field-level merged — rows[-1] is wrong
    # on this tab (append-unordered: Mac + cloud writers interleave out of time
    # order, and only macro_grab's rows carry spx_above_200sma).
    macro = merge_macro_rows(latest("macro"))
    gex_gate = {"gate": "NORMAL", "note": ""}
    try:
        spy = [r for r in latest("gex_regime")
               if (r.get("symbol") or "").upper() == "SPY"
               and (r.get("date") or "")[:10] == td]
        spy_row = latest_by_parsed_ts(spy)
        if spy_row:
            gex_gate = {"gate": spy_row.get("premium_gate") or "NORMAL",
                        "note": spy_row.get("note") or ""}
    except Exception:
        pass
    return plan, scan, acct, macro, gex_gate


def _alloc_coid(ticker: str) -> str:
    """Weekly id for standing-allocation top-ups — rebalance at most once/week,
    never re-buy the full sleeve every day."""
    y, w, _ = date.today().isocalendar()
    return f"casaa-ALLOC-{ticker}-{y}W{w:02d}"[:48]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Actually place orders on Alpaca PAPER (default: dry-run print only)")
    args = ap.parse_args()

    # HARD PAPER GUARD — fail SAFE to the paper endpoint on empty/missing base
    # (the only supported mode); a real non-paper URL is still refused.
    base = os.environ.get("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
    if args.execute and "paper-api" not in base:
        print(f"REFUSING: ALPACA_BASE_URL is not paper-api ({base}). This tool is PAPER ONLY.")
        return 2

    today = date.today().isoformat()
    plan_rows, scan, acct, macro, gexg = _read_plan_and_context()
    # FAIL-SAFE macro parse: no more VIX=16.0 / spx_above=True defaults on
    # missing data — unknown inputs mean degraded=True → 0.5 sizing multiplier.
    vix, spx_ok, macro_degraded = macro_sizing_context(macro)
    gex_caution = (gexg.get("gate") == "SELL_CAUTION")

    # Event blackout: high-impact US macro event (FOMC/CPI/NFP) inside 48h →
    # skip NEW premium-selling legs (same MacroFeed API trigger_alerts uses).
    blackout_event = None
    try:
        from src.macro_blackouts import MacroFeed
        blackout_event = MacroFeed.fetch().next_high_impact(within_hours=48)
    except Exception as e:
        print(f"  (event-blackout check failed: {e})")

    print(f"=== Alpaca paper executor · {today} · NLV ${acct['nlv']:,.0f} "
          f"excess ${acct['excess_liq'] or 0:,.0f} · VIX {vix if vix > 0 else '?'} ===")
    if macro_degraded:
        print("  ⚠ MACRO DATA DEGRADED — VIX and/or SPX-vs-200dma unknown from the "
              "macro tab; sizing HALVED (0.5× CAUTION-equivalent), never full-size.")
    if gexg.get("note"):
        print(f"  GEX: {gexg['note']}")
    if blackout_event:
        print(f"  ⛔ EVENT BLACKOUT: {blackout_event.get('event', '?')} in "
              f"{blackout_event.get('_minutes_until', '?')}min — premium-selling legs will be skipped")
    if not plan_rows:
        print("No daily_plan rows for today (run build_daily_plan.py first). Nothing to do.")
        return 0
    print(f"Executing the {len(plan_rows)}-row daily_plan (recommendation = execution)\n")

    from src import alpaca
    # Index scan_results by (ticker, strategy) so an income plan row can rebuild
    # its option order; and current positions to rebalance standing allocation.
    scan_idx = {}
    for p in scan:
        if (p.get("date") or "")[:10] == today:
            scan_idx[((p.get("ticker") or "").upper(), _norm_strat(p.get("strategy")))] = p
    try:
        posval = {p.get("symbol", ""): _f(p.get("market_value")) for p in alpaca.get_positions()}
    except Exception:
        posval = {}

    # Build the order list: each entry carries its plan-row key for fill_status.
    orders = []   # (key, spec, qty, coid)
    statuses = {}  # key -> fill_status (for rows we DON'T place)
    for r in plan_rows:
        leg = (r.get("leg") or "").lower()
        tk = (r.get("ticker") or "").upper()
        strat = _norm_strat(r.get("strategy"))
        key = (leg, tk, strat)

        if leg in ("core", "hedge", "protector"):
            # Held sleeves — rebalance toward target, never re-buy the full sleeve.
            target = _f(r.get("notional"))
            cur = posval.get(tk, 0.0)
            gap = round(target - cur, 2)
            if gap < max(1.0, 0.15 * target):     # within 15% of target → hold
                statuses[key] = "held (at target)"
                print(f"  HOLD {tk:6} {leg:9} — ${cur:,.0f}/${target:,.0f} at target")
                continue
            spec = {"kind": "equity", "symbol": tk, "side": "buy",
                    "notional": gap, "label": f"{leg.upper()} {tk} +${gap:,.0f}→target"}
            orders.append((key, spec, 0, _alloc_coid(tk)))
            print(f"  PLAN {spec['label']}  [rebalance]")

        elif leg == "growth":
            spec = {"kind": "equity", "symbol": tk, "side": "buy",
                    "notional": _f(r.get("notional")),
                    "label": f"GROWTH {tk} ${_f(r.get('notional')):,.0f}"}
            orders.append((key, spec, 0, f"casaa-{today}-GROWTH-{tk}"[:48]))
            print(f"  PLAN {spec['label']}  [equity]")

        elif leg == "income":
            skip = income_skip_reason(strat, gex_caution, blackout_event)
            if skip:
                statuses[key] = skip
                detail = ("GEX SELL_CAUTION (short gamma)" if "GEX" in skip else
                          f"event blackout ({(blackout_event or {}).get('event', '?')} <48h)")
                print(f"  SKIP {strat:10} {tk:6} — {detail}")
                continue
            pick = scan_idx.get((tk, strat))
            if not pick:
                statuses[key] = "skipped:no scan_results match"
                print(f"  SKIP {strat:10} {tk:6} — no matching scan_results pick")
                continue
            spec, reason = pick_to_order(pick)
            if spec is None:
                statuses[key] = f"skipped:{reason}"[:40]
                print(f"  SKIP {strat:10} {tk:6} — {reason}")
                continue
            qty = contracts_for(pick, acct["nlv"], acct["excess_liq"], vix, spx_ok,
                                degraded=macro_degraded)
            if qty <= 0:
                statuses[key] = "skipped:sized to 0"
                print(f"  SKIP {spec['label']} — sized to 0 contracts")
                continue
            orders.append((key, spec, qty, client_order_id(today, pick)))
            print(f"  PLAN {spec['label']}  ×{qty}  [{spec['kind']}]")
        else:
            statuses[key] = f"skipped:unknown leg {leg}"

    if not args.execute:
        print(f"\n[DRY-RUN] {len(orders)} orders planned from the daily_plan. "
              f"Re-run with --execute to place on PAPER.")
        return 0

    existing = {o.get("client_order_id") for o in alpaca.get_orders(status="all", limit=500)}
    placed = 0
    for key, spec, qty, coid in orders:
        if coid in existing:
            statuses[key] = "filled (already placed)"
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
            statuses[key] = "filled"
            print(f"  ✓ PLACED {spec['label']} ×{qty}")
        except Exception as e:
            statuses[key] = f"failed:{e}"[:60]
            print(f"  ✗ FAILED {spec['label']} — {e}")

    _writeback_fill_status(today, statuses)
    print(f"\nPlaced {placed}/{len(orders)} orders on Alpaca PAPER (daily_plan executed).")
    return 0


def _writeback_fill_status(today: str, statuses: dict) -> None:
    """Record each plan row's outcome back onto the daily_plan tab, so the PWA
    shows filled / held / skipped per row — the audit trail."""
    try:
        from src import sheets as sh, schema as S
        client = sh.authenticate()
        ss = sh._open_sheet(client)
        ws = ss.worksheet(S.DailyPlanRow.TAB_NAME)
        vals = ws.get_all_values()
        if len(vals) < 2:
            return
        hdr = vals[0]
        ci = {h: i for i, h in enumerate(hdr)}
        for row in vals[1:]:
            if (row[ci["date"]] or "")[:10] != today:
                continue
            key = ((row[ci["leg"]] or "").lower(),
                   (row[ci["ticker"]] or "").upper(),
                   _norm_strat(row[ci["strategy"]]))
            if key in statuses and ci.get("fill_status") is not None:
                row[ci["fill_status"]] = statuses[key]
        ws.update("A1", vals, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"  (fill_status writeback skipped: {e})")


if __name__ == "__main__":
    raise SystemExit(main())
