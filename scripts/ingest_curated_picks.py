#!/usr/bin/env python3
"""ingest_curated_picks.py — classify external (Motley Fool) picks into roles and
upsert the `curated_picks` tab. The MF READ is done in-session by Claude via Chrome
MCP (the crons are headless and cannot reach MF); this script consumes the emitted
picks JSON. Pure classifier (classify_picks) + a writer that mirrors build_daily_plan.

  python scripts/ingest_curated_picks.py --from-json /abs/path/picks.json [--dry]
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY_DAYS = 45        # a Buy is "recent" for CSP-overlay purposes
OVERLAY_PCT = 8.0        # ...and price within this % of adjusted rec price


def _days_between(a: str, b: str) -> int:
    from datetime import date as _d
    try:
        ya, ma, da = map(int, a[:10].split("-")); yb, mb, db = map(int, b[:10].split("-"))
        return abs((_d(yb, mb, db) - _d(ya, ma, da)).days)
    except Exception:
        return 10**6


def _overlay_eligible(sc: dict, today: str) -> bool:
    rec = sc.get("rec_date") or ""
    if _days_between(rec, today) > OVERLAY_DAYS:
        return False
    price, adj = sc.get("price"), sc.get("adj_rec_price")
    try:
        if price is None or adj in (None, 0):
            return False
        return abs(float(price) - float(adj)) / float(adj) * 100.0 <= OVERLAY_PCT
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def classify_picks(data: dict, today: str) -> list:
    """Map a picks JSON → CuratedPickRow list. A ticker may get multiple roles
    (e.g. reference + overlay) — one row per (ticker, role)."""
    from src import schema as S
    now = S.now_sgt_iso()
    founda = {t.upper() for t in data.get("foundational", [])}
    watch = {t.upper() for t in data.get("new_recs", [])} | {t.upper() for t in data.get("rankings", [])}
    sc_by_t = {(sc.get("ticker") or "").upper(): sc for sc in data.get("scorecard", [])}
    rows = []

    def mk(tk: str, role: str, note: str = "") -> None:
        sc = sc_by_t.get(tk, {})
        rows.append(S.CuratedPickRow(
            date=today, ticker=tk, role=role, mf_type=str(sc.get("type") or ""),
            rec_date=str(sc.get("rec_date") or ""), rec_price=str(sc.get("adj_rec_price") or sc.get("price") or ""),
            market_cap=str(sc.get("market_cap") or ""),
            return_since_rec=("" if sc.get("return_since_rec") is None else str(sc.get("return_since_rec"))),
            return_vs_sp=("" if sc.get("return_vs_sp") is None else str(sc.get("return_vs_sp"))),
            moneyball_score=("" if sc.get("moneyball") is None else str(sc.get("moneyball"))),
            source="motley_fool", note=note, updated_at=now))

    # reference = every active scorecard name; core = Foundational; watchlist = new/rankings;
    # overlay = recent Buy near rec price.
    for tk, sc in sc_by_t.items():
        mk(tk, "reference")
        if tk in founda:
            mk(tk, "core", "Foundational")
        if tk in watch:
            mk(tk, "watchlist", "New Rec / Ranking")
        if _overlay_eligible(sc, today):
            mk(tk, "overlay", "recent Buy near rec price — CSP target")
    # watchlist names that aren't on the scorecard yet (brand-new rec)
    for tk in watch - set(sc_by_t):
        mk(tk, "watchlist", "New Rec / Ranking")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-json", required=True)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.from_json).read_text())
    today = (data.get("as_of") or date.today().isoformat())[:10]
    rows = classify_picks(data, today)
    print(f"=== curated_picks · {today} · {len(rows)} role-rows ===")
    for r in rows:
        print(f"  {r.ticker:6} {r.role:9} {r.note}")
    if args.dry or not rows:
        print(f"[{'DRY' if args.dry else 'NO-OP'}] not written."); return 0

    from src.sync import load_env
    from src import sheets as sh, schema as S
    load_env()
    client = sh.authenticate(); ss = sh._open_sheet(client)
    sh.ensure_headers(client, S.CuratedPickRow.TAB_NAME, S.CuratedPickRow.HEADERS)
    ws = ss.worksheet(S.CuratedPickRow.TAB_NAME)
    existing = ws.get_all_values()
    keep = [existing[0]] if existing else [S.CuratedPickRow.HEADERS]
    # replace only motley_fool rows for `today`; preserve other sources/days
    src_i, date_i = S.CuratedPickRow.HEADERS.index("source"), 0
    keep += [r for r in (existing[1:] if existing else [])
             if r and not (r[date_i][:10] == today and len(r) > src_i and r[src_i] == "motley_fool")]
    keep += [r.to_row() for r in rows]
    ws.clear(); ws.update("A1", keep, value_input_option="USER_ENTERED")
    print(f"✓ Wrote {len(rows)} rows to curated_picks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
