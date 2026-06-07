# Private Read Path — Design (Firebase Auth + Firestore serving-mirror)

> **Date:** 2026-06-07 · **Status:** Approved (Caspar, 2026-06-07) · **Data model:** Row-capped mirror v1 (Caspar: "you decide what's best")
> **Origin:** Architecture audit `docs/2026-06-06-architecture-audit.md` — CRITICAL finding: portfolio world-readable via public Sheet.

## Problem

The PWA reads ~39 Google Sheet tabs via the **public** gviz CSV endpoint. `SHEET_ID` is hardcoded in the shipped JS bundle (`pwa/src/data.ts:3`) and the Sheet is "anyone with the link," so anyone who view-sources the deployed PWA (or reads the public repo) can `curl` both books — holdings, cost basis, account sizes (~$8–9k + ~S$59k), live P&L. This is a continuous, un-revocable leak of real financial data.

## Northstar alignment

The Northstar is to make Caspar + Sarah serious money via real-time, accurate, actionable intel across ETFs/stocks/options. A leaking dashboard is a liability against that goal (front-running risk, privacy). This fix protects the asset without slowing the engine.

## Goal

Only Caspar + Sarah can read portfolio data. Google Sheet stays the hand-editable single source of truth. Zero downtime during cutover. $0 cost.

## Non-goals (YAGNI)

- No multi-tenant / "millions" scale — 1–2 users, data grows not users.
- No PWA → backend write path (decisions stay localStorage; the audit confirmed they never wrote back anyway).
- No replacing Sheets as source of truth — cron writers and hand-edits are untouched.
- No Redis/queue/DB (audit flagged these as over-engineering).

## Architecture (one new hop)

```
[31 cron writers] ──writes──▶ Google Sheet  (source of truth; RESTRICTED last)
                                   │
        NEW: scripts/mirror_to_firestore.py  (GitHub Action, ~every 15 min)
                                   │  reads only PWA-needed tabs · hash-diff · writes changed
                                   ▼
                              Firestore  (private — Auth + security rules)
                                   ▲
                                   │  authenticated read (Google sign-in, allowlisted)
                              PWA  (data.ts transport: gviz-CSV ▶ Firestore; parsing unchanged)
```

## Components (all code = Claude)

### 1. Mirror writer — `scripts/mirror_to_firestore.py` + `.github/workflows/mirror-firestore.yml`
- Cron every 15 min (matches PWA poll cadence; staleness ≤15 min is acceptable).
- Reads the exact tab list the PWA fetches (derived from `pwa/src/data.ts`) via existing `src/sheets.py` read helpers.
- Writes each tab as one Firestore doc: `tabs/{tabName} = { rows: [ {col: val, …}, … ], updatedAt, rowCount, sourceHash }`.
- **Row-cap:** keep most-recent ~400 rows (or ~120 days where dated) per tab → stays under Firestore's 1 MB/doc limit. Tabs that still exceed ~900 KB are chunked into `tabs/{tabName}` + `tabs/{tabName}__1`, `__2`… (rare).
- **Hash-diff:** skip writing a tab whose `sourceHash` is unchanged → minimal Firestore writes, free tier safe.
- **Atomic + fail-safe:** write per-tab; on a tab read failure, skip + log, never wipe the last-good doc.
- Auth via `firebase-admin` + service-account JSON (`FIREBASE_SERVICE_ACCOUNT_JSON`, CI secret + `.env`). No-op with a clear log if the secret is unset (mirrors the project's inert-without-key pattern).

### 2. Security rules — `firestore.rules`
```
rules_version = '2';
service cloud.firestore {
  match /databases/{db}/documents {
    match /tabs/{doc} {
      allow read: if request.auth != null
                  && request.auth.token.email in ['<caspar>', '<sarah>'];
      allow write: if false;   // only the service account (admin SDK) writes
    }
  }
}
```

### 3. PWA auth gate
- Firebase Google sign-in replaces the localStorage PIN.
- Only allowlisted emails reach the dashboard; others see a "not authorized" state.
- Sign-out control in Settings.

### 4. PWA data layer — `pwa/src/data.ts` + `pwa/src/lib/firebase.ts`
- New `firebase.ts`: init app + auth + firestore from the **web config** (public-safe by design — security is Auth + rules, not secrecy; lives in the bundle).
- Swap `fetchTab`/`fetchTabByName` transport: read the Firestore `tabs/{name}` doc and return `doc.rows` (already the row-object array the parsers expect). All downstream parsing/derivation unchanged → minimal blast radius.
- Keep a dev fallback flag (`VITE_DATA_SOURCE=gviz|firestore`) so we can build/deploy the Firestore path while the Sheet is still public, then cut over.

## Error handling
- **Mirror:** per-tab try/except → skip+log, keep last-good; summary exit code (0 ok / 1 partial / 2 fatal-auth), matching `sync.py`.
- **PWA:** explicit states — signing-in, not-authorized, load-error (retry), empty-tab. These become the first reusable components of deliverable #3.

## Testing
- Unit (pytest, mock Firestore client): tab→doc mapping, row-cap, chunk-overflow, hash-diff skip, fail-safe on bad tab, inert-without-secret.
- Rules: Firebase emulator test — allowlisted email reads, non-allowlisted denied, client write denied.
- PWA: manual sign-in + read verification post-setup.

## Work split
- **Caspar (Firebase Console — Claude cannot auth his Google account):** create project · enable Firestore + Auth (Google provider) · add allowed emails (his + Sarah's) · generate service-account key → GitHub secret `FIREBASE_SERVICE_ACCOUNT_JSON` · copy web config → hand to Claude. Runbook: `docs/runbooks/setup-firebase.md`.
- **Claude (all code):** mirror writer + workflow + tests, `firestore.rules`, PWA `firebase.ts` + auth gate + `data.ts` swap, the runbook.

## Rollout (no broken window)
1. Build everything (Firestore path behind `VITE_DATA_SOURCE` flag, default still gviz).
2. Caspar sets up Firebase + pastes config/secret.
3. Mirror runs → Firestore populated.
4. Flip PWA to `firestore`, deploy, verify reads behind auth.
5. **Then** Caspar restricts the Sheet sharing → public leak closed, app already private.

## Cost
Firebase Spark (free): ~10k reads + ~5k writes/day for 2 users vs 50k/20k limits → **$0**.

## Inputs needed at config time
- The two Google emails for the allowlist.
- Confirm Google sign-in (vs. Sarah using Caspar's login → allowlist of 1).
