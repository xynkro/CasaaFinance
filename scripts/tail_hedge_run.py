#!/usr/bin/env python3
"""
tail_hedge_run.py — the convex TAIL HEDGE layer (the missing leg).

The system "protected" by REDUCE_ONLY — selling growth in a cautious regime,
i.e. capitulating low. An all-rounded book instead HOLDS the growth and owns a
small, convex insurance that pays off in a crash. This layer recommends that
insurance: a defined-risk SPY put-spread, sized as a small % of NLV, gated by
regime + vol.

Sizing philosophy (a hedge has negative carry, so size it deliberately):
  • Keep a cheap STANDING hedge (~1% of NLV) — insurance is bought BEFORE the
    fire, when it's cheap.
  • Lean IN when the regime sours (REDUCE_ONLY / weak trend) but vol is still
    affordable — that's the highest-value window.
  • DON'T chase after VIX has already spiked (expensive) — scale down.
  • Hard cap ~2% of NLV; a hedge that bleeds the account isn't a hedge.

Output: a DecisionRow (bucket="hedge", strategy="HEDGE", source="tail_hedge")
per account → decision_queue. Recommendation only; the user executes.

Usage:
  python scripts/tail_hedge_run.py --dry     # print the recommendation
  python scripts/tail_hedge_run.py           # write to decision_queue
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.bsm import norm_cdf  # noqa: E402

# Hedge structure (SPY put-spread).
SHORT_OTM = 0.05      # short put ~5% below spot
LONG_OTM = 0.12       # long put ~12% below spot (the wing)
TARGET_DTE = 60       # 45-75d gives time for a move to develop
HEDGE_CAP_PCT = 0.020 # never spend > 2% of NLV on the hedge
RF = 0.04


# ──────────────────── Pure, tested logic ────────────────────────────────────

def hedge_budget_pct(regime: str, vix: float, spx_above_200dma: bool) -> float:
    """Fraction of NLV to allocate to the standing tail hedge.

    Buy insurance cheap and keep it; lean in as the regime weakens; don't chase
    a vol spike. Returns 0.0 only in clear euphoria (very low vol, strong trend)
    where carry isn't worth it.
    """
    vix = vix or 16.0
    reg = (regime or "").upper()

    base = 0.010  # 1% standing hedge
    if "REDUCE" in reg or "CAUTION" in reg or "HALT" in reg or not spx_above_200dma:
        base += 0.006   # regime souring → more insurance (while still affordable)
    if vix < 13 and spx_above_200dma:
        base = max(0.004, base - 0.004)  # dead-calm bull → trim carry, keep a sliver
    if vix > 28:
        base *= 0.5     # already spiked → expensive, don't chase
    return round(min(base, HEDGE_CAP_PCT), 4)


def put_spread_strikes(spot: float, short_otm: float = SHORT_OTM,
                       long_otm: float = LONG_OTM) -> tuple[float, float]:
    """SPY put-spread strikes (rounded to $1), (short, long). short > long."""
    short = round(spot * (1 - short_otm))
    long_ = round(spot * (1 - long_otm))
    if long_ >= short:
        long_ = short - 1
    return float(short), float(long_)


def _bsm_put(S: float, K: float, T: float, sigma: float, r: float = RF) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


def spread_debit_per_contract(spot: float, short_k: float, long_k: float,
                              vix: float, dte: int) -> float:
    """Estimated net debit ($) for one SPY put-spread, priced off VIX as IV."""
    T = max(dte / 365.0, 1e-6)
    iv = max((vix or 16.0) / 100.0, 0.05)
    debit = _bsm_put(spot, short_k, T, iv) - _bsm_put(spot, long_k, T, iv)
    return max(0.0, debit) * 100.0


def contracts_for(budget: float, debit_per_contract: float) -> int:
    if budget <= 0 or debit_per_contract <= 0:
        return 0
    return int(budget // debit_per_contract)


def build_hedge(nlv: float, spot: float, vix: float, regime: str,
                spx_above_200dma: bool, dte: int = TARGET_DTE) -> dict | None:
    """Hedge recommendation for one account, or None if not warranted.

    Prefers a convex SPY put-spread when the budget fits >=1 contract; otherwise
    (a small account where one index spread blows the cap) falls back to a
    fractional VIXM long-vol allocation. Both are real hedges, sized to fit.
    """
    if nlv <= 0:
        return None
    pct = hedge_budget_pct(regime, vix, spx_above_200dma)
    budget = nlv * pct
    if budget <= 0:
        return None

    if spot > 0:
        short_k, long_k = put_spread_strikes(spot)
        debit = spread_debit_per_contract(spot, short_k, long_k, vix, dte)
        qty = contracts_for(budget, debit)
        if qty >= 1:
            width = short_k - long_k
            cost = debit * qty
            return {
                "type": "put_spread", "short_strike": short_k, "long_strike": long_k,
                "width": width, "dte": dte, "qty": qty,
                "debit_per_contract": round(debit, 2), "cost": round(cost, 2),
                "budget": round(budget, 2), "budget_pct": pct,
                "max_payoff": round(width * 100 * qty - cost, 2),
                "covers_notional": round(short_k * 100 * qty, 0),
            }

    # Too small for an index spread → fractional long-vol ETF (VIXM).
    return {"type": "vol_etf", "ticker": "VIXM", "dollars": round(budget, 2),
            "budget_pct": pct, "budget": round(budget, 2)}


# ──────────────────── I/O ────────────────────────────────────────────────────

def _read_context():
    """Per-account NLV + SPY spot (spx/10) + vix + regime from the sheet."""
    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    def latest(tab):
        try:
            r = ss.worksheet(tab).get_all_values()
            return [dict(zip(r[0], x)) for x in r[1:] if any(x)][-1] if len(r) > 1 else {}
        except Exception:
            return {}

    macro = latest("macro")
    vix = float(macro.get("vix") or 16.0)
    spx = float(macro.get("spx") or 0.0)
    spot = spx / 10.0 if spx > 0 else 0.0       # SPY ≈ SPX/10
    usd_sgd = float(macro.get("usd_sgd") or 1.30) or 1.30
    posture = latest("exposure_posture")
    regime = posture.get("recommendation") or posture.get("regime") or "STANDARD"
    spx_above = str(macro.get("spx_above_200sma", "True")).lower() not in ("false", "0", "")

    accts = {}
    try:
        c = latest("snapshot_caspar")
        accts["caspar"] = float(c.get("net_liq_usd") or 0)
    except Exception:
        pass
    try:
        s = latest("snapshot_sarah")
        nlv_sgd = float(s.get("net_liq_sgd") or 0)
        accts["sarah"] = nlv_sgd / usd_sgd
    except Exception:
        pass
    return accts, spot, vix, regime, spx_above, client


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print only, no sheet write")
    args = ap.parse_args()

    accts, spot, vix, regime, spx_above, client = _read_context()
    today = date.today().isoformat()
    expiry = (date.today() + timedelta(days=TARGET_DTE))
    # next monthly-ish expiry: just use the target date (recommendation, user picks the listed one)
    expiry_iso = expiry.strftime("%Y%m%d")

    print(f"=== Tail hedge · {today} · SPY≈{spot:.0f} · VIX {vix} · regime {regime} "
          f"· SPX>200dma {spx_above} ===")

    from src import schema as S
    rows = []
    for acct, nlv in accts.items():
        h = build_hedge(nlv, spot, vix, regime, spx_above)
        if not h:
            print(f"  {acct}: no hedge warranted (NLV ${nlv:,.0f})")
            continue

        if h["type"] == "put_spread":
            thesis = (
                f"Convex tail hedge: SPY {h['short_strike']:.0f}/{h['long_strike']:.0f} put "
                f"spread ×{h['qty']}, ~{h['dte']}d, cost ${h['cost']:.0f} "
                f"({h['budget_pct']*100:.1f}% NLV) — pays up to ${h['max_payoff']:.0f} on a "
                f"~12% SPY drop, covering ~${h['covers_notional']:,.0f}. Lets you HOLD growth "
                f"instead of selling it in a scare."
            )
            print(f"  {acct}: {thesis}")
            rows.append(S.DecisionRow(
                date=today, account=acct, ticker="SPY", bucket="hedge",
                thesis_1liner=f"SPY put-spread tail hedge ({h['budget_pct']*100:.1f}% NLV)",
                conv=3, entry=h["debit_per_contract"] / 100.0, target=0.0, status="watching",
                strategy="HEDGE", right="P", strike=h["short_strike"], expiry=expiry_iso,
                premium_per_share=round(h["debit_per_contract"] / 100.0, 2), delta=0.0,
                annual_yield_pct=0.0, breakeven=h["short_strike"] - h["debit_per_contract"] / 100.0,
                cash_required=h["cost"], iv_rank=0.0, thesis_confidence=0.6, thesis=thesis,
                source="tail_hedge", qty=h["qty"],
                accumulation_plan=f"Buy SPY {h['short_strike']:.0f}/{h['long_strike']:.0f}P "
                                  f"~{h['dte']}d ×{h['qty']} for ~${h['cost']:.0f} when vol is calm.",
                gates="",
            ))
        else:  # vol_etf
            thesis = (
                f"Tail hedge (small-account sizing): allocate ~${h['dollars']:.0f} "
                f"({h['budget_pct']*100:.1f}% NLV) to VIXM long-vol. One index put-spread "
                f"would blow the 2%-NLV carry cap on this account, so the convex sleeve is "
                f"held as fractional VIXM instead — a passive long-vol ballast that rises in a "
                f"crash. Lets you HOLD growth instead of selling it in a scare."
            )
            print(f"  {acct}: {thesis}")
            rows.append(S.DecisionRow(
                date=today, account=acct, ticker="VIXM", bucket="hedge",
                thesis_1liner=f"VIXM long-vol tail hedge ({h['budget_pct']*100:.1f}% NLV)",
                conv=3, entry=0.0, target=0.0, status="watching",
                strategy="HEDGE", right="", strike=0.0, expiry="",
                premium_per_share=0.0, delta=0.0, annual_yield_pct=0.0, breakeven=0.0,
                cash_required=h["dollars"], iv_rank=0.0, thesis_confidence=0.6, thesis=thesis,
                source="tail_hedge", qty=0,
                accumulation_plan=f"Buy ~${h['dollars']:.0f} VIXM as a standing long-vol hedge.",
                gates="",
            ))

    if args.dry or not rows:
        print(f"\n[{'DRY' if args.dry else 'NO-OP'}] {len(rows)} hedge recommendation(s).")
        return 0

    from src import sheets as sh
    sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
    sh.append_rows(client, S.DecisionRow.TAB_NAME, [r.to_row() for r in rows])
    print(f"\n✓ Wrote {len(rows)} hedge recommendation(s) to decision_queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
