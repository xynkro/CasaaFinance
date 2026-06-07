# Private Read Path — Implementation Plan

> **For Claude:** Execute via superpowers:subagent-driven-development (backend Python and PWA TS are disjoint → parallel-safe). Project commits ONLY when Caspar asks — stage explicit files, never `git add -A`. Runner is `.venv/bin/python` (no bare `python`).

**Goal:** Make the PWA read portfolio data privately (Firebase Auth + Firestore serving-mirror) so restricting the public Sheet closes the leak without breaking the app.

**Architecture:** A 15-min GitHub Action mirrors the 39 PWA-needed Sheet tabs into Firestore docs `tabs/{name}={rows,updatedAt,rowCount,sourceHash}` (row-capped, hash-diffed). The PWA swaps its `fetchTab`/`fetchTabByName` transport from gviz-CSV to a Firestore doc read behind Google sign-in; security rules allow reads only to an allowlist. Sheet stays source of truth.

**Tech Stack:** Python `firebase-admin` (mirror) · existing `src/sheets.py` (read) · PWA `firebase` JS SDK (auth+firestore) · Vite env flags · Firestore security rules.

**Tab list (39, from `data.ts` `fetchDashboard`):** daily_brief_latest, snapshot_caspar, snapshot_sarah, positions_caspar, positions_sarah, options, technical_scores, wheel_next_leg, exit_plans, options_defense, wsr_summary, decision_queue, macro, wsr_archive, regime_signals, exposure_posture, screen_candidates, tv_signals, risk_parity_audit, live_prices, earnings_calendar, economic_calendar, news_sentiment, insider_transactions, analyst_consensus, api_usage, gov_confluence_signals, congress_trades, snapshot_alpaca, positions_alpaca, harvest_scan, iv_surface_scan, uoa_alerts, scan_results, paper_benchmark, gex_regime, daily_plan, macro_lean, curated_picks.

---

## Task 1 — Mirror writer core + tests  *(backend)*

**Files:** Create `scripts/mirror_to_firestore.py`, `tests/test_mirror_firestore.py`; modify `requirements.txt` (+`firebase-admin`).

**Behavior (TDD — write tests first, mock the Firestore client):**
- `mirror_tabs(read_tab, db, tabs=PWA_TABS, cap=400)`: for each tab, `rows = read_tab(name)`; cap to last `cap` rows; `sourceHash = sha256(json(rows))`; if existing doc's `sourceHash` matches → skip (return "unchanged"); else `db.collection("tabs").document(name).set({rows, updatedAt, rowCount, sourceHash})`.
- `_cap_rows(rows, cap)`: returns last `cap` (rows are already chronological; keep tail).
- `_chunk_if_oversize(name, payload)`: if `len(json) > 900_000`, split `rows` into `tabs/{name}`, `tabs/{name}__1`, … each <900KB; else single doc.
- **Inert-without-key:** `_db()` returns `None` (clear log, exit 0) if `FIREBASE_SERVICE_ACCOUNT_JSON` unset — mirrors `gmail_client` pattern.
- **Fail-safe:** per-tab try/except → log + skip (keep last-good doc); never delete. Exit 0 all-ok / 1 partial / 2 fatal-auth.
- Reads tabs via `src.sheets` (authenticate() → worksheet(name).get_all_records()); confirm exact helper name when implementing.

**Tests:** unchanged-hash skip; cap keeps last N; oversize → chunks; bad-tab skip keeps going + exit 1; inert returns None + exit 0. Run `.venv/bin/python -m pytest tests/test_mirror_firestore.py -v`.

## Task 2 — Mirror workflow  *(backend)*

**Files:** Create `.github/workflows/mirror-firestore.yml`. Cron `*/15 * * * *` + `workflow_dispatch`. Steps: checkout → setup-python 3.12 → `pip install -r requirements.txt` → `python scripts/mirror_to_firestore.py`. Env: `FIREBASE_SERVICE_ACCOUNT_JSON`, `OAUTH_TOKEN_JSON` (Sheet read). Add `set -euo pipefail` to the run step (audit fix #4-adjacent).

## Task 3 — Firestore rules  *(backend/config)*

**Files:** Create `firestore.rules`, `firebase.json` (rules pointer). Rule: `match /tabs/{doc}` → `allow read: if request.auth != null && request.auth.token.email in ['<EMAIL_CASPAR>','<EMAIL_SARAH>']; allow write: if false;`. Emails are placeholders Caspar fills. Add an emulator rules-test if quick.

## Task 4 — PWA Firebase module + deps  *(frontend)*

**Files:** Create `pwa/src/lib/firebase.ts`; modify `pwa/package.json` (+`firebase`), `pwa/.env.example`. `firebase.ts`: init app/auth/firestore from `import.meta.env.VITE_FIREBASE_*` (web config is public-safe); export `auth`, `signInWithGoogle()`, `signOutUser()`, `onUser(cb)`, and `readFirestoreTab<T>(name): Promise<T[]>` (reads `tabs/{name}`, returns `doc.data().rows ?? []`, transparently re-joins `__1/__2` chunks).

## Task 5 — data.ts transport swap  *(frontend)*

**Files:** Modify `pwa/src/data.ts:78-93`. Gate on `import.meta.env.VITE_DATA_SOURCE` (`'gviz'` default | `'firestore'`): `fetchTab(name)` and `fetchTabByName(name)` both call `readFirestoreTab(name)` when firestore, else current CSV path. Keep all parsing/derivation downstream untouched.

## Task 6 — Auth gate + sign-out  *(frontend)*

**Files:** Modify `pwa/src/App.tsx` (PIN gate), `pwa/src/pages/SettingsPage.tsx` (sign-out). When `VITE_DATA_SOURCE==='firestore'`: gate dashboard on `onUser`; signed-out → Google sign-in screen; signed-in-but-not-allowlisted → "not authorized" (rules also enforce); else render. PIN path remains for gviz/dev.

## Task 7 — Reusable async-state components  *(frontend — seeds Deliverable #3)*

**Files:** Create `pwa/src/components/AsyncStates.tsx` — `<LoadingState>` (skeleton), `<EmptyState>`, `<ErrorState onRetry>`, `<NotAuthorized>`, `<SignInScreen>`. Accessible (role, aria-live), responsive, themed. Wire into App.tsx + the dashboard shell.

## Task 8 — Setup runbook  *(do FIRST — unblocks Caspar)*

**Files:** Create `docs/runbooks/setup-firebase.md` — click-by-click: create project · enable Firestore (production mode) · enable Auth → Google provider · add allowed emails · generate service-account key → GitHub secret `FIREBASE_SERVICE_ACCOUNT_JSON` · copy web config → the 6 `VITE_FIREBASE_*` values · deploy rules. Plus the cutover order + the final "restrict the Sheet" step.

## Task 9 — Docs + env  *(backend)*

**Files:** Modify `.env.example` (+`FIREBASE_SERVICE_ACCOUNT_JSON`), `README.md` (read path note), `MANUAL_TRIGGERS.md` (+mirror-firestore row).

---

## Rollout (after build)
Build (flag defaults to gviz) → Caspar runs runbook + pastes config/secret → mirror populates Firestore → flip `VITE_DATA_SOURCE=firestore`, deploy, verify reads behind auth → **Caspar restricts the Sheet** → leak closed.
