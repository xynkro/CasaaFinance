#!/usr/bin/env python3
"""
gex_regime.py — daily dealer Gamma Exposure (GEX) regime map for SPY / QQQ.

WHAT IT DOES
  Pulls the near-dated options chains (≤45 DTE), recomputes per-strike dealer
  dollar-gamma from Black-Scholes, and aggregates a net-GEX regime per symbol:
    • POSITIVE_PINNED  — dealers long gamma → vol suppressed, the tape pins/chops
    • NEGATIVE_TREND   — dealers short gamma → vol expansion, gap/trend risk
    • NEUTRAL          — longs and shorts roughly cancel
  Plus the gamma-flip ("zero-gamma") level and the call/put walls.

WHY
  For a premium seller this is a risk gate, not a price forecast: positive-gamma
  days are friendly to CSP/CC/credit spreads (theta decays, price pins inside the
  short strikes); negative-gamma days carry gap risk straight through them. The
  PWA shows it as a pre-market banner; the paper executor reads `premium_gate`
  to stand down new premium-selling entries on NEGATIVE_TREND days.

  Evidence: Barbon & Buraschi (2021), "Gamma Fragility" (SSRN 3725454). The
  dealer-positioning sign convention is the standard retail heuristic — most
  meaningful on index/ETF chains, noise on thin single names (see src/gex.py).

Read-only against yfinance; writes the gex_regime tab (one row per symbol).

Usage:
  python scripts/gex_regime.py --dry
  python scripts/gex_regime.py
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import gex  # noqa: E402

SYMBOLS = ("SPY", "QQQ")
DTE_MAX = 45            # near-dated expiries carry the regime-relevant gamma
STRIKE_BAND = 0.15     # ignore strikes beyond ±15% of spot (gamma ≈ 0 there)
R = 0.045

# CBOE delayed-quotes JSON — free, no key, and the rare free source that carries
# real OPEN INTEREST + per-option greeks (yfinance returns OI=0 for SPY/QQQ).
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"


def _parse_occ(occ: str) -> tuple[date, str, float] | None:
    """ROOT + YYMMDD + C/P + strike×1000(8) → (expiry, right, strike)."""
    i = 0
    while i < len(occ) and not occ[i].isdigit():
        i += 1
    body = occ[i:]
    if len(body) < 15:
        return None
    try:
        exp = date(2000 + int(body[0:2]), int(body[2:4]), int(body[4:6]))
        right = body[6].upper()
        strike = int(body[7:15]) / 1000.0
    except (ValueError, IndexError):
        return None
    if right not in ("C", "P") or strike <= 0:
        return None
    return exp, right, strike


def _fetch_cboe(symbol: str) -> dict:
    url = CBOE_URL.format(sym=symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


def build_book(symbol: str) -> tuple[float, list[dict]]:
    """Return (spot, option specs) for `symbol` across expiries ≤ DTE_MAX,
    sourced from CBOE delayed quotes (OI + IV per strike)."""
    payload = _fetch_cboe(symbol)
    data = payload.get("data", {}) or {}
    spot = float(data.get("current_price") or data.get("close") or 0)
    if spot <= 0:
        return 0.0, []

    today = date.today()
    lo, hi = spot * (1 - STRIKE_BAND), spot * (1 + STRIKE_BAND)
    book: list[dict] = []
    for o in data.get("options", []) or []:
        parsed = _parse_occ(str(o.get("option") or ""))
        if not parsed:
            continue
        exp, right, strike = parsed
        if strike < lo or strike > hi:
            continue
        dte = (exp - today).days
        if dte < 0 or dte > DTE_MAX:
            continue
        try:
            oi = int(o.get("open_interest") or 0)
            iv = float(o.get("iv") or 0)
        except (TypeError, ValueError):
            continue
        if oi <= 0 or iv <= 0.01 or iv > 3.0:
            continue
        T = max(dte, 0.5) / 365.0          # floor so 0DTE gamma stays finite
        book.append({"strike": strike, "right": right, "oi": oi,
                     "T": T, "sigma": iv})
    return spot, book


def analyze(symbol: str) -> dict | None:
    spot, book = build_book(symbol)
    if spot <= 0 or not book:
        return None
    net = gex.net_gex(book, spot, R)
    gross = gex.gross_gex(book, spot, R)
    flip = gex.gamma_flip_level(book, spot, R)
    cw = gex.call_wall(book, spot, R)
    pw = gex.put_wall(book, spot, R)
    regime = gex.classify_regime(net, gross)
    gate = gex.premium_gate(regime)
    note = gex.regime_note(symbol, spot, net, flip, cw, pw, regime)
    flip_pct = ((spot - flip) / spot * 100.0) if flip else 0.0
    return {
        "symbol": symbol, "spot": spot, "net_gex": net, "gross": gross,
        "gamma_flip": flip or 0.0, "flip_distance_pct": flip_pct,
        "call_wall": cw or 0.0, "put_wall": pw or 0.0,
        "regime": regime, "premium_gate": gate, "note": note,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print only, no sheet write")
    args = ap.parse_args()

    from src.sync import load_env
    from src import schema as S
    load_env()

    today = date.today().isoformat()
    now_iso = S.now_sgt_iso()
    rows = []
    print(f"=== GEX regime · {today} ===\n")
    for sym in SYMBOLS:
        try:
            r = analyze(sym)
        except Exception as e:
            print(f"  {sym}: analyze failed: {e}")
            continue
        if not r:
            print(f"  {sym}: no usable chain data — skipped")
            continue
        print(f"  {r['regime']:16} [{r['premium_gate']}]  {r['note']}")
        rows.append(S.GexRegimeRow(
            date=today, symbol=r["symbol"], spot=round(r["spot"], 2),
            net_gex=round(r["net_gex"], 0), gamma_flip=round(r["gamma_flip"], 2),
            flip_distance_pct=round(r["flip_distance_pct"], 2),
            call_wall=round(r["call_wall"], 2), put_wall=round(r["put_wall"], 2),
            regime=r["regime"], premium_gate=r["premium_gate"],
            note=r["note"], updated_at=now_iso))

    if args.dry or not rows:
        print(f"\n[{'DRY' if args.dry else 'NO-OP'}] {len(rows)} regime rows.")
        return 0

    from src import sheets as sh
    client = sh.authenticate()
    ss = sh._open_sheet(client)
    sh.ensure_headers(client, S.GexRegimeRow.TAB_NAME, S.GexRegimeRow.HEADERS)
    ws = ss.worksheet(S.GexRegimeRow.TAB_NAME)
    existing = ws.get_all_values()
    keep = [existing[0]] if existing else [S.GexRegimeRow.HEADERS]
    keep += [r for r in (existing[1:] if existing else []) if r and r[0][:10] != today]
    keep += [r.to_row() for r in rows]
    sh.upsert_tab(ws, keep)
    print(f"\n✓ Wrote {len(rows)} rows to gex_regime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
