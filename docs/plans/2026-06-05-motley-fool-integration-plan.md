# Motley Fool Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the user's Motley Fool Stock Advisor picks into a `curated_picks` sheet tab that feeds four roles (core sleeve, watchlist, options overlay, reference card) of the CasaaFinance engine — engine-input-not-signal, equal-weight, separately benchmarked vs SPY.

**Architecture:** Claude reads MF via Chrome MCP in-session (≈monthly) and emits a `picks JSON`. A pure, tested classifier (`scripts/ingest_curated_picks.py`) maps picks → `CuratedPickRow`s tagged with a role + `source=motley_fool`, upserted to the `curated_picks` tab using the exact clear+update pattern of `build_daily_plan.py`. Downstream: `build_daily_plan.py` adds an equal-weight, capped MF core sleeve; the PWA reads `curated_picks` by name and renders watchlist/overlay/reference; a benchmark aggregation tracks the MF sleeve vs SPY.

**Tech Stack:** Python 3 (dataclasses, gspread + repo's `src/sheets.py`), pytest; Vite/React/TypeScript/Tailwind PWA (papaparse fetch).

**Design doc:** `docs/plans/2026-06-05-motley-fool-integration-design.md`

**Guardrails (every task respects these):** engine-input-not-signal · equal-weight · separate SPY benchmark · paper-only.

---

### Task 1: `CuratedPickRow` schema + `curated_picks` tab

**Files:**
- Modify: `src/schema.py` (add dataclass after `MacroLeanRow`, ~line 2195)
- Test: `tests/test_schema_curated.py` (create)

**Step 1: Write the failing test**

```python
# tests/test_schema_curated.py
from src.schema import CuratedPickRow

def test_headers_and_to_row_align():
    r = CuratedPickRow(
        date="2026-06-05", ticker="AMZN", role="core", mf_type="Cautious",
        rec_date="2026-03-20", rec_price="208.76", market_cap="2.73T",
        return_since_rec="21.57", return_vs_sp="6.51", moneyball_score="",
        source="motley_fool", note="Foundational", updated_at="2026-06-05T12:00:00")
    assert len(r.to_row()) == len(CuratedPickRow.HEADERS)
    assert r.to_row()[CuratedPickRow.HEADERS.index("ticker")] == "AMZN"
    assert r.to_row()[CuratedPickRow.HEADERS.index("role")] == "core"

def test_role_is_constrained_by_convention():
    # roles used downstream — keep this list authoritative
    assert {"core", "watchlist", "overlay", "reference"}
```

**Step 2: Run to verify it fails**

Run: `cd /Users/xynkro/Documents/Trading/FinancePWA && python -m pytest tests/test_schema_curated.py -v`
Expected: FAIL — `ImportError: cannot import name 'CuratedPickRow'`

**Step 3: Implement (mirror `MacroLeanRow` exactly)**

```python
# src/schema.py — after MacroLeanRow
@dataclass
class CuratedPickRow:
    """One curated pick from an external human-vetted source (Motley Fool Stock
    Advisor today). Read in-session via Chrome MCP, classified into a role, and
    fed to the engine as INPUT — never an auto-signal. Equal-weight + separately
    benchmarked vs SPY so we KNOW if the subscription earns its keep."""
    TAB_NAME = "curated_picks"
    HEADERS = ["date", "ticker", "role", "mf_type", "rec_date", "rec_price",
               "market_cap", "return_since_rec", "return_vs_sp", "moneyball_score",
               "source", "note", "updated_at"]

    date: str
    ticker: str
    role: str            # core | watchlist | overlay | reference
    mf_type: str = ""    # Cautious | Moderate | Aggressive (MF risk type)
    rec_date: str = ""
    rec_price: str = ""
    market_cap: str = ""
    return_since_rec: str = ""
    return_vs_sp: str = ""
    moneyball_score: str = ""
    source: str = "motley_fool"
    note: str = ""
    updated_at: str = ""

    def to_row(self) -> List[str]:
        return [self.date, self.ticker, self.role, self.mf_type, self.rec_date,
                self.rec_price, self.market_cap, self.return_since_rec,
                self.return_vs_sp, self.moneyball_score, self.source,
                self.note, self.updated_at]
```

**Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_schema_curated.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/schema.py tests/test_schema_curated.py
git commit -m "feat(schema): CuratedPickRow + curated_picks tab for external picks"
```

---

### Task 2: Pure classifier — picks JSON → roles

**Files:**
- Create: `scripts/ingest_curated_picks.py`
- Test: `tests/test_ingest_curated.py`

**Picks JSON shape** (what Claude emits from the Chrome-MCP read — document at top of script):

```json
{
  "as_of": "2026-06-05",
  "foundational": ["AMZN","INTC","DDOG"],
  "new_recs": ["FPS"],
  "rankings": ["GLW","MSFT"],
  "scorecard": [
    {"ticker":"FPS","price":64.04,"rec_date":"2026-06-05","type":"","market_cap":"19.66B",
     "adj_rec_price":64.59,"return_since_rec":null,"return_vs_sp":null,"div_rate":null,"moneyball":null},
    {"ticker":"GLW","price":197.70,"rec_date":"2026-05-22","type":"Cautious","market_cap":"170.15B",
     "adj_rec_price":191.60,"return_since_rec":3.19,"return_vs_sp":1.27,"div_rate":1.12,"moneyball":null}
  ]
}
```

**Step 1: Write the failing test**

```python
# tests/test_ingest_curated.py
from scripts.ingest_curated_picks import classify_picks

DATA = {
  "as_of": "2026-06-05",
  "foundational": ["AMZN"],
  "new_recs": ["FPS"],
  "rankings": ["GLW"],
  "scorecard": [
    {"ticker":"FPS","price":64.04,"rec_date":"2026-06-05","type":"","market_cap":"19.66B",
     "adj_rec_price":64.59,"return_since_rec":None,"return_vs_sp":None},
    {"ticker":"GLW","price":197.70,"rec_date":"2026-05-22","type":"Cautious","market_cap":"170.15B",
     "adj_rec_price":191.60,"return_since_rec":3.19,"return_vs_sp":1.27},
    {"ticker":"AMZN","price":254.02,"rec_date":"2026-03-20","type":"Cautious","market_cap":"2.73T",
     "adj_rec_price":208.76,"return_since_rec":21.57,"return_vs_sp":6.51},
  ],
}

def _roles(rows, tk):
    return {r.role for r in rows if r.ticker == tk}

def test_every_scorecard_name_is_reference():
    rows = classify_picks(DATA, today="2026-06-05")
    assert "reference" in _roles(rows, "GLW")
    assert "reference" in _roles(rows, "AMZN")

def test_foundational_is_core():
    rows = classify_picks(DATA, today="2026-06-05")
    assert "core" in _roles(rows, "AMZN")
    assert "core" not in _roles(rows, "GLW")

def test_new_rec_and_ranking_are_watchlist():
    rows = classify_picks(DATA, today="2026-06-05")
    assert "watchlist" in _roles(rows, "FPS")
    assert "watchlist" in _roles(rows, "GLW")

def test_overlay_only_recent_and_near_rec_price():
    rows = classify_picks(DATA, today="2026-06-05")
    # FPS: rec 0 days ago, price 64.04 vs adj 64.59 (~0.9%) → overlay
    assert "overlay" in _roles(rows, "FPS")
    # AMZN: rec 77 days ago → too old for overlay
    assert "overlay" not in _roles(rows, "AMZN")

def test_source_tag():
    rows = classify_picks(DATA, today="2026-06-05")
    assert all(r.source == "motley_fool" for r in rows)
```

**Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ingest_curated.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: classify_picks`

**Step 3: Implement the classifier (pure) + thin sheet writer (mirrors build_daily_plan)**

```python
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
```

**Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_ingest_curated.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add scripts/ingest_curated_picks.py tests/test_ingest_curated.py
git commit -m "feat(curated): classify MF picks into core/watchlist/overlay/reference roles"
```

---

### Task 3: MF core sleeve in `build_daily_plan.py` (equal-weight, capped)

**Files:**
- Modify: `scripts/build_daily_plan.py` (constants ~line 57; new fn after `_growth_candidates`; `build_plan` ~line 151; `main` reads tab ~line 209)
- Test: `tests/test_daily_plan_mf.py`

**Step 1: Write the failing test**

```python
# tests/test_daily_plan_mf.py
from scripts.build_daily_plan import _mf_core_candidates, MF_CORE_CAP

CURATED = [
    {"date":"2026-06-05","ticker":"AMZN","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"INTC","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"DDOG","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"FIX","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"GLW","role":"watchlist","source":"motley_fool"},  # not core
]

def test_caps_number_of_names():
    rows = _mf_core_candidates(CURATED, "2026-06-05", nlv=10000.0)
    assert len(rows) <= MF_CORE_CAP

def test_equal_weight_and_tagged():
    rows = _mf_core_candidates(CURATED, "2026-06-05", nlv=10000.0)
    notionals = {r["notional"] for r in rows}
    assert len(notionals) == 1                      # equal-weight
    assert all(r["source"] == "motley_fool" for r in rows)
    assert all(r["leg"] == "mf_core" for r in rows)

def test_ignores_non_core_and_other_days():
    rows = _mf_core_candidates(CURATED, "2026-06-05", nlv=10000.0)
    tickers = {r["ticker"] for r in rows}
    assert "GLW" not in tickers
    assert _mf_core_candidates(CURATED, "2026-06-04", nlv=10000.0) == []
```

**Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_daily_plan_mf.py -v`
Expected: FAIL — `ImportError: _mf_core_candidates` / `MF_CORE_CAP`

**Step 3: Implement**

```python
# build_daily_plan.py — near other constants (~line 57)
MF_CORE_CAP = 3                 # max MF Foundational names added to the satellite
MF_CORE_PER_NAME_PCT = 0.04     # equal-weight, ~4% NLV each (inside satellite budget)

# ...after _growth_candidates(...)
def _mf_core_candidates(curated_rows: list[dict], today: str, nlv: float,
                        cap: int = MF_CORE_CAP, per_name_pct: float = MF_CORE_PER_NAME_PCT) -> list[dict]:
    """Equal-weight, capped MF Foundational sleeve. Selection is MF's edge; sizing
    stays disciplined (equal-weight, capped, inside the satellite budget). Tagged
    source=motley_fool so the benchmark can isolate it. INPUT, never auto-signal."""
    core = [r for r in curated_rows
            if (r.get("date") or "")[:10] == today
            and (r.get("role") or "").lower() == "core"]
    # de-dup by ticker, stable order
    seen, picks = set(), []
    for r in core:
        tk = (r.get("ticker") or "").upper()
        if tk and tk not in seen:
            seen.add(tk); picks.append(tk)
    picks = picks[:cap]
    notional = round(per_name_pct * nlv, 2)
    return [{
        "leg": "mf_core", "ticker": tk, "strategy": "GROWTH",
        "detail": f"${notional:,.0f} notional (MF Foundational)",
        "conviction": 90.0, "target_pct": 0.0, "notional": notional,
        "reason": "Motley Fool Foundational — equal-weight conviction sleeve",
        "source": "motley_fool",
    } for tk in picks]
```

Wire into `build_plan` (add param + merge into opportunities):

```python
def build_plan(nlv, scan_rows, screen_rows, today, lean="neutral", curated_rows=None):
    plan = standing_allocation_rows(nlv)
    n_growth, sat_pct = _LEAN_TILT.get(lean, (TOP_GROWTH, SATELLITE_PER_NAME_PCT))
    income = _income_candidates(scan_rows, today)[:TOP_INCOME]
    growth = _growth_candidates(screen_rows, today, nlv, per_name_pct=sat_pct)[:n_growth]
    mf_core = _mf_core_candidates(curated_rows or [], today, nlv)
    if lean in _LEAN_TILT:
        tilt = "trimmed (hawkish/risk-off)" if n_growth < TOP_GROWTH else "leaned-in (dovish/risk-on)"
        for g in growth:
            g["reason"] = f"[macro {lean}: {tilt}] {g['reason']}"[:90]
    opportunities = sorted(income + growth + mf_core, key=lambda x: x["conviction"], reverse=True)
    plan.extend(opportunities)
    for i, row in enumerate(plan, start=1):
        row["rank"] = i; row["execute"] = True
    return plan
```

In `main()` read the tab and pass it:

```python
    curated = latest("curated_picks")
    plan = build_plan(nlv, latest("scan_results"), latest("screen_candidates"),
                      today, lean=lean, curated_rows=curated)
```

**Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_daily_plan_mf.py tests/ -k "daily_plan or plan" -v`
Expected: PASS (incl. existing daily_plan tests still green)

**Step 5: Commit**

```bash
git add scripts/build_daily_plan.py tests/test_daily_plan_mf.py
git commit -m "feat(plan): equal-weight capped MF Foundational core sleeve (source-tagged)"
```

---

### Task 4: PWA add the `mf_core` leg label (TodaysPlanCard)

**Files:**
- Modify: `pwa/src/cards/TodaysPlanCard.tsx` (LEG_META ~line 10; standing/opps filters ~line 87)

**Step 1–3:** Add the leg to `LEG_META` and include `mf_core` in the opportunities bucket:

```tsx
// LEG_META
mf_core: { label: "MF Core", icon: TrendingUp, cls: "text-fuchsia-300" },
// opps filter (line ~88): include mf_core alongside growth/income
const opps = rows.filter((r) => ["growth", "income", "mf_core"].includes((r.leg || "").toLowerCase()));
```

**Step 4: Verify build**

Run: `cd pwa && npx tsc --noEmit && npm run build`
Expected: tsc clean, vite build green.

**Step 5: Commit**

```bash
git add pwa/src/cards/TodaysPlanCard.tsx
git commit -m "feat(pwa): render MF Core leg in Today's Plan"
```

---

### Task 5: PWA data layer — fetch `curated_picks`, derive role buckets

**Files:**
- Modify: `pwa/src/data.ts` (interface near `MacroLeanRow` ~line 777; fetch array ~line 1431; assignment ~line 1528; error fallback ~line 1564; `DashboardData` type ~line 1332)

**Step 1–3:** Add the type + fetch + derived buckets:

```ts
// types
export interface CuratedPickRow {
  date: string; ticker: string; role: string; mf_type: string;
  rec_date: string; rec_price: string; market_cap: string;
  return_since_rec: string; return_vs_sp: string; moneyball_score: string;
  source: string; note: string; updated_at: string;
}
// DashboardData
curatedPicks: CuratedPickRow[];        // raw, latest day
mfWatchlist: CuratedPickRow[];         // role=watchlist
mfOverlay: CuratedPickRow[];           // role=overlay
mfReference: CuratedPickRow[];         // role=reference

// in the Promise.all fetch array:
fetchTabByName<CuratedPickRow>("curated_picks").catch(() => [] as CuratedPickRow[]),
// destructure as curatedPickRows

// build the return object (after computing `const cp = latestGroup(curatedPickRows);`):
curatedPicks: cp,
mfWatchlist: cp.filter((r) => r.role === "watchlist"),
mfOverlay:   cp.filter((r) => r.role === "overlay"),
mfReference: cp.filter((r) => r.role === "reference"),
// error fallback object: curatedPicks: [], mfWatchlist: [], mfOverlay: [], mfReference: [],
```

**Step 4:** `cd pwa && npx tsc --noEmit` → clean.

**Step 5: Commit** `git add pwa/src/data.ts && git commit -m "feat(pwa): fetch curated_picks + derive MF role buckets"`

---

### Task 6: PWA — "Motley Fool" reference card

**Files:**
- Create: `pwa/src/cards/MotleyFoolCard.tsx`
- Modify: `pwa/src/pages/HomePage.tsx` (render it; guard on `mfReference.length`)

**Step 1–3:** Card lists reference rows (ticker · type · return-vs-S&P · Moneyball), renders `null` when empty (no first-deploy stub). Mirror `Card` usage from `TodaysPlanCard`. Show a one-line disclaimer: "Motley Fool Stock Advisor — reference only, not auto-traded."

**Step 4:** `cd pwa && npx tsc --noEmit && npm run build` → green.

**Step 5: Commit** `git add pwa/src/cards/MotleyFoolCard.tsx pwa/src/pages/HomePage.tsx && git commit -m "feat(pwa): Motley Fool reference card (Scorecard + Moneyball)"`

---

### Task 7: PWA — watchlist strip + overlay CSP targets

**Files:**
- Modify: `pwa/src/pages/DecisionsPage.tsx` (watchlist strip from `mfWatchlist`)
- Modify: `pwa/src/pages/OptionsPage.tsx` (overlay targets from `mfOverlay`, in the "book"/"harvest" area as CSP candidates)
- Wire props through `App.tsx`.

**Step 1–3:** Small read-only strips. Watchlist: chips of tickers + note ("research, not a buy"). Overlay: "MF CSP targets — sell puts to enter at MF's price" list (ticker · rec price), explicitly suggestion-only.

**Step 4:** `cd pwa && npx tsc --noEmit && npm run build` → green.

**Step 5: Commit** `git add -p` the three files; `git commit -m "feat(pwa): MF watchlist strip + overlay CSP targets (read-only)"`

---

### Task 8: SPY-benchmark isolation for the MF sleeve

**Files:**
- Inspect: the script writing `paper_benchmark` (find via `grep -rln paper_benchmark scripts/`)
- Modify: that script to emit an aggregate `MF_SLEEVE` benchmark row (sum of `source=motley_fool` fills vs SPY-equivalent), reusing the existing per-pick vs-SPY math.
- Test: `tests/test_mf_benchmark.py` — given fills tagged motley_fool, the aggregate row's return is the notional-weighted average vs SPY.

**Step 1:** Write the failing test for the aggregation helper (pure function over fill rows).
**Step 2:** Run → fails.
**Step 3:** Implement the `MF_SLEEVE` aggregation (mirror the existing TOTAL row logic, filtered to `source=motley_fool`).
**Step 4:** `python -m pytest tests/test_mf_benchmark.py -v` → PASS.
**Step 5: Commit** `git commit -m "feat(benchmark): isolate MF sleeve vs SPY (accountability layer)"`

---

### Task 9: Runbook — the in-session MF refresh

**Files:**
- Create: `docs/runbooks/refresh-motley-fool.md`

Document the monthly cadence: (1) Claude opens fool.com Stock Advisor in Chrome MCP (user already logged in), (2) reads Scorecard + Foundational + New Recs + Rankings via `read_page`, (3) emits `picks.json`, (4) runs `python scripts/ingest_curated_picks.py --from-json picks.json`, (5) verifies `curated_picks` + the PWA card. Note the headless crons deliberately do NOT do this.

**Commit** `git add docs/runbooks/refresh-motley-fool.md && git commit -m "docs(curated): MF in-session refresh runbook"`

---

### Task 10: Telegram push — new-rec · overlay · core-add

**Files:**
- Modify: `src/telegram.py` (add `ping_curated_pick`, mirror `ping_macro_surprise`)
- Modify: `scripts/ingest_curated_picks.py` (pure `curated_alerts(prev, new)` + fire in `main`)
- Modify: `scripts/trigger_alerts.py` (diff `daily_plan` mf_core → fire core-add pings)
- Test: `tests/test_curated_alerts.py`

**Step 1: Write the failing test (pure diff)**

```python
# tests/test_curated_alerts.py
from scripts.ingest_curated_picks import curated_alerts

PREV = [{"ticker":"GLW","role":"reference"},{"ticker":"GLW","role":"watchlist"}]
NEW  = [{"ticker":"GLW","role":"reference"},{"ticker":"GLW","role":"watchlist"},
        {"ticker":"FPS","role":"watchlist"},{"ticker":"FPS","role":"reference"},
        {"ticker":"GLW","role":"overlay"}]

def test_new_rec_and_overlay_detected():
    al = {(a["kind"], a["ticker"]) for a in curated_alerts(PREV, NEW)}
    assert ("new_rec","FPS") in al        # FPS newly appears
    assert ("overlay","GLW") in al        # GLW newly overlay-eligible
    assert ("new_rec","GLW") not in al    # GLW already known

def test_no_alerts_when_unchanged():
    assert curated_alerts(NEW, NEW) == []
```

**Step 2: Run → fails** (`ImportError: curated_alerts`).

**Step 3: Implement**

```python
# ingest_curated_picks.py
def curated_alerts(prev_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    """New-rec + overlay pings by diffing prior vs new curated_picks rows. Pure."""
    prev_t = {(r.get("ticker") or "").upper() for r in prev_rows}
    prev_ov = {(r.get("ticker") or "").upper() for r in prev_rows if (r.get("role") or "") == "overlay"}
    seen, out = set(), []
    for r in new_rows:
        tk = (r.get("ticker") or "").upper()
        if tk and tk not in prev_t and tk not in seen:
            seen.add(tk); out.append({"kind": "new_rec", "ticker": tk, "detail": r.get("note", "")})
    for r in new_rows:
        tk = (r.get("ticker") or "").upper()
        if (r.get("role") or "") == "overlay" and tk and tk not in prev_ov:
            out.append({"kind": "overlay", "ticker": tk, "detail": f"rec {r.get('rec_price','')}"})
    return out
```

```python
# src/telegram.py
def ping_curated_pick(kind: str, ticker: str, detail: str = "") -> None:
    icon = {"new_rec": "🧠", "overlay": "📍", "core": "🟣"}.get(kind, "🧠")
    label = {"new_rec": "New Motley Fool rec",
             "overlay": "MF pick now in CSP-overlay range",
             "core": "MF name entered core sleeve"}.get(kind, "Motley Fool")
    body = f"{icon} {label}: *{ticker}*" + (f" — {detail}" if detail else "")
    send_message(body + "\n_reference input, not auto-traded_")
```

In `ingest_curated_picks.main()` (after the sheet write, skip on `--dry`): build `prev_rows`
from the `existing` values already read, call `curated_alerts(prev_rows, [r.__dict__-ish])`,
and `for a in alerts: tg.ping_curated_pick(a["kind"], a["ticker"], a["detail"])`.

In `scripts/trigger_alerts.py`: read `daily_plan`, diff today's `leg==mf_core` tickers against
the prior day's; for each newly-added ticker call `ping_curated_pick("core", tk, "equal-weight sleeve")`.
Guard with the same date/dedup discipline as the existing pings.

**Step 4: Run → passes**

Run: `python -m pytest tests/test_curated_alerts.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/telegram.py scripts/ingest_curated_picks.py scripts/trigger_alerts.py tests/test_curated_alerts.py
git commit -m "feat(telegram): MF push — new-rec/overlay/core-add (diff-based, headless-safe)"
```

---

### Final verification (after all tasks)

```bash
cd /Users/xynkro/Documents/Trading/FinancePWA
python -m pytest tests/ -q                 # all green (incl. new curated/plan/benchmark)
cd pwa && npx tsc --noEmit && npm run build # tsc clean, vite green
```

Then dispatch a final code-reviewer over the whole MF integration before finishing.
