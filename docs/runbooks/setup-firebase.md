# Setup: Private Read Path (Firebase) — Caspar's checklist

Goal: make the PWA read your data **privately** so you can restrict the public Sheet and close the leak. ~15 min of Console clicking. **I (Claude) can't do these steps — they need your Google identity + consent.** When done, hand me the values marked **→ give Claude**.

> Order matters. Do steps 1–6 now. **Do NOT restrict the Sheet until step 8** — that's the very last thing, after the private path is verified, so the app never breaks.

## 1. Create the Firebase project (~2 min)
- Go to <https://console.firebase.google.com> → **Add project** → name it e.g. `casaafinance` → you can disable Google Analytics → Create.

## 2. Enable Firestore (~2 min)
- Left nav → **Build → Firestore Database → Create database**.
- Start in **Production mode** (locked by default — our rules open read to just you two).
- Pick the region closest to you (e.g. `asia-southeast1` Singapore). **This is permanent.**

## 3. Enable Google sign-in (~1 min)
- **Build → Authentication → Get started → Sign-in method → Google → Enable** → set support email → Save.
- **⚠️ REQUIRED: authorize the PWA's domain.** Auth only allows sign-in from listed domains (default: `localhost`, `*.firebaseapp.com`). The PWA is served from GitHub Pages, so add it:
  **Authentication → `Settings` tab → Authorized domains → Add domain → `xynkro.github.io`.**
  (Without this, "Continue with Google" fails with `auth/unauthorized-domain`.)

## 4. Allowlist your two emails (~1 min)
- These go in `firestore.rules` (I generate the file). Tell me the two Google accounts that may sign in:
  - **→ give Claude:** your email (default `the.disruptive.comp@gmail.com`) + **Sarah's Google email** (or "Sarah uses my login" → just one).

## 5. Service-account key for the mirror (~2 min) — SECRET
- **Project settings (gear) → Service accounts → Generate new private key** → downloads a JSON.
- GitHub → repo `xynkro/CasaaFinance` → **Settings → Secrets and variables → Actions → New repository secret**:
  - Name: `FIREBASE_SERVICE_ACCOUNT_JSON` · Value: paste the entire JSON file contents.
- ⚠️ This key is a write credential — **never commit it, never paste it in chat.** It lives only in GitHub Secrets.

## 6. Web config for the PWA (~1 min) — public-safe
- **Project settings → General → Your apps → Web app (`</>`)** → register app (no Hosting needed) → copy the `firebaseConfig` object (apiKey, authDomain, projectId, storageBucket, messagingSenderId, appId).
  - **→ give Claude:** those 6 values. They're safe to ship in the bundle (security is enforced by Auth + rules, not secrecy) — I'll wire them into the deploy workflow.

## 7. Deploy the rules + cut over (I do this, on your go)
- I push `firestore.rules` (you deploy via Console **Firestore → Rules → paste → Publish**, or I do it via `firebase deploy --only firestore:rules` if you install the CLI).
- I flip the PWA to the Firestore read path and deploy. The 15-min mirror Action populates Firestore.
- **We verify:** you open the PWA → Google sign-in → data loads. A non-allowlisted account is denied.

## 8. LAST — restrict the Sheet (you, ~60 sec) → closes the leak
- Only after step 7 verifies the private path works:
- Open the Google Sheet → **Share** → change **"Anyone with the link"** to **Restricted** (just your account). This 404s every public CSV endpoint and ends the leak. The PWA is already reading Firestore, so nothing breaks.

---
**Summary of what to hand me:** (a) the 2 allowlist emails, (b) confirmation the `FIREBASE_SERVICE_ACCOUNT_JSON` secret is set, (c) the 6 `firebaseConfig` web values. Then I finish the cutover and you do step 8.
