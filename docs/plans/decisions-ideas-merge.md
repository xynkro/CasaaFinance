# Plan — Merge Options › Ideas (Strategy Notes) into Decisions

**Status:** active
**Owner:** Caspar
**Created:** 2026-04-30

## Why

The brain (Opus 4.7 in `wsr-full.yml` / `wsr-lite.yml`) currently writes to **two
parallel sheets** with overlapping content:

- `decision_queue` → PWA **Decisions tab** (strategic, glanceable — bucket + 1-liner thesis + conv 1-5)
- `option_recommendations` → PWA **Options › Ideas tab** (tactical, options-spec-rich — strategy + strike + expiry + premium + Δ + thesis)

Per `prompts/cron_wsr_full.md` §6c and §6d, the brain *intentionally double-writes*
share-entry ideas (e.g. `BUY_DIP MDT`) to both sheets, just rendered at different
levels of detail. For share entries, every options-spec field in
`option_recommendations` is zero — it's a square peg in an options-shaped hole.

**Goal:** one unified ranked weekly queue. Schema absorbs the optional
options-spec fields. Decisions card renders share rows minimally and option rows
with full execution detail.

## Defaults (controller-set, override before exec)

| Q | Default |
|---|---|
| Status vocab | Decisions' set: `pending/watching/filled/killed/expired`. Map old: `proposed→pending`, `executed→filled`, `skipped→killed` |
| Conviction | Keep BOTH: `conv` (1-5 int, gut feel) + `thesis_confidence` (0.0-1.0 float, brain analytic signal) |
| Sheet name | Leave as `decision_queue` (no rename churn) |
| Ideas-tab kill | Staged: Phase C ships unified card, Phase D removes tab + dead code after one rotation |

## Tasks

### Task A — Backend schema + push script (additive, backward-compatible)

**Goal:** Extend `decision_queue` schema with optional options-spec fields. Update
`push_decisions.py` to accept the new fields with safe defaults. Existing brain
emissions (without the new fields) keep working unchanged.

**Files:**
- `src/schema.py` — extend `DecisionRow` HEADERS + dataclass fields + `to_row()`
- `scripts/push_decisions.py` — accept new fields, default empty/0 when absent
- (no PWA changes in this task)

**New fields appended to `DecisionRow.HEADERS` (after `status`):**

```
"strategy",            # "" | "BUY_DIP" | "TRIM" | "CSP" | "CC" | "PMCC" | "LONG_CALL" | "LONG_PUT"
"right",               # "" | "C" | "P"
"strike",              # 0 for share entries
"expiry",              # "" | "YYYYMMDD"
"premium_per_share",   # 0 for shares
"delta",               # 0 for shares
"annual_yield_pct",    # 0 for shares
"breakeven",           # 0 if not applicable
"cash_required",       # 0 if not applicable
"iv_rank",             # 0 if not applicable
"thesis_confidence",   # 0.0-1.0 (existing recs schema's analytic confidence)
"thesis",              # full multi-sentence brain thesis (separate from thesis_1liner)
"source",              # "" | "wsr_full" | "wsr_lite" | "manual"
```

**Upsert key change:** the old key is `(date_prefix, account, ticker)`. With the
expanded schema we need to support multiple strategies on the same ticker (e.g.
BUY_DIP MDT *and* CSP MDT in the same week). New key:
`(date_prefix, account, ticker, strategy, strike)` — same compound key as
`push_recommendations.py` already uses. Empty `strategy`/`strike=0` collapse
naturally for legacy share-only rows.

**Constraints:**
- Backward-compat: existing rows in the sheet (9-col HEADERS) must not error on
  upsert; legacy rows that don't have the new columns should be retained.
- Idempotent: running with the same JSON twice produces no duplicate rows.
- `--dry` flag still works.

**Acceptance:**
- `python scripts/push_decisions.py --dry --json-file fixtures/...` accepts a
  payload that mixes share + option rows and prints a clean upsert plan.
- Live run with `--dry` against the production sheet shows zero data loss
  (existing rows preserved).

**Don't touch in this task:**
- Brain prompts (Task B)
- PWA code (Task C)
- `push_recommendations.py` (Task D — deferred)

### Task B — Brain prompt switch

**Goal:** Both WSR brain prompts emit ONE unified JSON to `push_decisions.py`
instead of two separate JSONs to `push_decisions.py` + `push_recommendations.py`.

**Files:**
- `prompts/cron_wsr_full.md` — collapse §6c + §6d into a single §6c writing the
  unified schema. CC eligibility rule and thesis-content rule move to the
  unified §6c. Drop §6d entirely.
- `prompts/cron_wsr_lite.md` — same collapse (its §5c + §5d).

**The unified JSON shape (replaces both old shapes):**

```json
{
  "date": "2026-05-01",
  "decisions": [
    {
      "ticker":            "MDT",
      "account":           "sarah",
      "bucket":            "quality",
      "thesis_1liner":     "Wide-moat medical at SMA50 support. Entry $84 → target $96.",
      "conv":              4,
      "entry":             84.00,
      "target":            96.00,
      "status":            "pending",
      "strategy":          "BUY_DIP",
      "right":             "",
      "strike":            0,
      "expiry":            "",
      "premium_per_share": 0,
      "delta":             0,
      "annual_yield_pct":  0,
      "breakeven":         0,
      "cash_required":     8400,
      "iv_rank":           0,
      "thesis_confidence": 0.70,
      "thesis":            "<2-4 sentence brain thesis: WHY, WHY NOW, WHAT CANCELS, WHAT TO WATCH>",
      "source":            "wsr_full"
    },
    {
      "ticker":            "AAPL",
      "account":           "sarah",
      "bucket":            "blue_chip",
      "thesis_1liner":     "AAPL CSP $250P 35DTE — collect premium in low-IV regime.",
      "conv":              4,
      "entry":             250.00,
      "target":            245.50,
      "status":            "pending",
      "strategy":          "CSP",
      "right":             "P",
      "strike":            250.00,
      "expiry":            "20260619",
      "premium_per_share": 4.50,
      "delta":             0.20,
      "annual_yield_pct":  14.0,
      "breakeven":         245.50,
      "cash_required":     25000,
      "iv_rank":           28,
      "thesis_confidence": 0.65,
      "thesis":            "<brain thesis>",
      "source":            "wsr_full"
    }
  ]
}
```

**Constraints:**
- Keep all existing CC-eligibility rules — just relocated under §6c.
- The `bucket` field stays for share entries (quality / blue_chip / core / etc.).
  For option entries, bucket can be the bucket of the underlying.
- Schedule and other workflow steps unchanged.
- The agent must always populate the new fields (with empty/0 for share entries)
  so the downstream sheet rows are well-formed.

**Don't touch in this task:**
- `push_decisions.py` is already updated by Task A — just call it the same way.
- `push_recommendations.py` references stay (Task D removes them).
- PWA (Task C).

### Task C — PWA Decisions card upgrade (Ideas tab kept for parity check)

**Goal:** Decisions card renders BOTH share-style and option-style rows from the
unified `decision_queue`. Ideas tab stays for now (parity check).

**Files:**
- `pwa/src/data.ts` — extend `DecisionRow` TypeScript type with the new optional
  fields (all stringly-typed since they come from sheets).
- `pwa/src/pages/DecisionsPage.tsx` — `DecisionCard` gains an options-spec sub-row
  (premium / yield / Δ / BE / IVR / Conf bar) when `strategy ∈ {CSP, CC, PMCC,
  LONG_CALL, LONG_PUT}`. Reuse the visual pattern from
  `pwa/src/cards/RecommendationCard.tsx`.
- `pwa/src/components/StockDetail.tsx` — surface the long-form `thesis` and
  `thesis_confidence` if present on the selected decision.

**Visual spec for option row (additive — appears below the existing thesis):**

```
[ premium $4.50 ] [ yield 14.0% ] [ Δ 0.20 ] [ BE $245.50 ] [ IVR 28 ]   [conf 65% ●●●○○]
```

Match the existing dark-glass / tabular-nums style from RecommendationCard.

**Constraints:**
- All new fields are optional. Rows with `strategy === ""` (legacy share-only or
  unset) render exactly as today.
- No layout shift for legacy decisions.
- Don't drop the Ideas subtab in this task (Phase D).
- Don't delete RecommendationCard.tsx in this task (Phase D).

**Acceptance:**
- After deploy, the Decisions tab on iPhone shows both share-style decisions
  (rendered as today) AND option-style decisions (with the new spec sub-row).
- Tap into an option-style decision opens StockDetail with the long-form thesis.
- Ideas tab still works exactly as before.
- One full WSR cycle produces matching content in Decisions vs Ideas (parity
  check window — manual verification by user).

### Task D — Ideas tab kill + cleanup (DEFERRED — execute after parity verified)

Not in this session. Triggered by user after one rotation of parity verification.

**Files (when run):**
- `pwa/src/pages/OptionsPage.tsx` — remove `"ideas"` subtab, leave 3 tabs: Defense / Book / Scan.
- `pwa/src/cards/RecommendationCard.tsx` — delete.
- `pwa/src/components/RecommendationDetailModal.tsx` — delete.
- `pwa/src/data.ts` — remove `OptionRecommendationRow` type + loader.
- `pwa/src/App.tsx` — drop `recommendations` state + `loadOptionRecommendations` plumbing.
- `scripts/push_recommendations.py` — delete (or shrink to deprecation no-op).
- `src/schema.py` — `OptionRecommendationRow` stays (history sheet preserved).

## Order

A → B → C, each shipping as its own commit on `main` (consistent with this
session's pattern). D deferred to a separate session.

## Risks

- **Schema column mismatch in Sheets:** `ensure_headers` rewrites row 1 if drift
  detected. Existing rows have 9 cols, new HEADERS has 22 cols — gspread will
  pad existing rows with blanks on reads. No data loss, just empty values for
  the new fields on legacy rows. Verified safe.
- **Brain prompt drift:** If §6c+§6d collapse breaks something subtle in the
  agent's reasoning, the next WSR cron may write malformed rows. Mitigation:
  Phase B includes manual `workflow_dispatch` validation before the next
  scheduled cron.
- **Ideas tab parity gap:** during the parity window (Phase C → D), users see
  the same idea twice (in Decisions AND Ideas). This is intentional — it's the
  cross-check that the unified schema captured everything.
