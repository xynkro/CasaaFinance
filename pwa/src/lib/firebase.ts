/**
 * Firebase transport for the private read path.
 *
 * The PWA's 39 data tabs are mirrored from the Google Sheet into Firestore
 * (collection `tabs`, doc id = tab name) by a backend GitHub Action. This
 * module is the client side of that contract: Google sign-in for the auth
 * gate, plus `readFirestoreTab` which returns the same row-object array the
 * existing CSV parsers expect.
 *
 * Security model: the Firebase WEB config below is public-safe by design —
 * access is enforced by Firebase Auth + Firestore security rules (an email
 * allowlist), NOT by keeping the config secret. We still read it from
 * import.meta.env so no real project values are committed to the repo.
 *
 * This module is only imported when VITE_DATA_SOURCE==='firestore' (both
 * App.tsx and data.ts gate the import on the flag), so initialising the
 * Firebase app at import time is safe — the default gviz path never loads
 * this file and therefore stays completely Firebase-free.
 */
import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  type Auth,
  type User,
} from "firebase/auth";
import {
  getFirestore,
  doc,
  getDoc,
  setDoc,
  serverTimestamp,
  type Firestore,
} from "firebase/firestore";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

if (!firebaseConfig.apiKey || !firebaseConfig.projectId) {
  // Loud failure: reaching this module means firestore mode is active, so a
  // missing config is a misconfiguration, not a soft-degrade case.
  throw new Error(
    "Firebase config missing — set VITE_FIREBASE_* env vars (see .env.example).",
  );
}

const app: FirebaseApp = initializeApp(firebaseConfig);

/** Firebase Auth instance. */
export const auth: Auth = getAuth(app);

/** Firestore instance (internal — reads go through readFirestoreTab). */
const db: Firestore = getFirestore(app);

/** Open the Google sign-in popup. Resolves to the signed-in user. */
export async function signInWithGoogle(): Promise<User> {
  const provider = new GoogleAuthProvider();
  // Always show the account chooser so a second user (e.g. Sarah) can pick
  // her own Google account rather than silently reusing a cached session.
  provider.setCustomParameters({ prompt: "select_account" });
  const result = await signInWithPopup(auth, provider);
  return result.user;
}

/** Sign the current user out. */
export async function signOutUser(): Promise<void> {
  await signOut(auth);
}

/**
 * Subscribe to auth-state changes. Fires immediately with the current user
 * (or null) and again on every sign-in/sign-out. Returns an unsubscribe fn.
 */
export function onUser(cb: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth, cb);
}

/**
 * Read one mirrored tab from Firestore and return its rows.
 *
 * Doc contract (shared with the backend mirror — do not deviate):
 *   collection `tabs`, doc id = tab name,
 *   shape `{ rows: Array<object>, updatedAt, rowCount, sourceHash, chunks }`.
 *
 * Oversized tabs are split: the base doc `tabs/{name}` carries `chunks = N`
 * and holds the first slice of `rows`; the remaining slices live in
 * `tabs/{name}__1`, `tabs/{name}__2`, … each with their own `rows`. We read
 * the base doc, then (if chunks > 0) read each numbered chunk in order and
 * concatenate every `rows` array, yielding the full row-object array exactly
 * as the existing parsers expect. A missing base doc returns [] (the same
 * empty-tab behaviour the gviz path tolerates via its per-tab catches).
 */
/**
 * Coerce every cell of a mirrored row back to a STRING.
 *
 * The gviz CSV path (Papa.parse) hands the app every field as a string, and the
 * whole PWA is built on that contract (e.g. `expiry.slice(4,6)`, `Number(strike)`).
 * Firestore, however, gets its rows from the backend's `get_all_records()`, which
 * types numeric cells as numbers and checkboxes as booleans — so `expiry` arrives
 * as `20260821` (number) and `(20260821).slice(...)` throws "slice is not a
 * function", white-screening the page. Re-stringifying here restores the gviz
 * contract for every consumer in one place. Booleans → "TRUE"/"" (gviz checkbox
 * style); null/undefined → "".
 */
function coerceRowToStrings(row: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k in row) {
    const v = row[k];
    out[k] =
      v == null ? "" : typeof v === "boolean" ? (v ? "TRUE" : "") : String(v);
  }
  return out;
}

export async function readFirestoreTab<T>(name: string): Promise<T[]> {
  const baseSnap = await getDoc(doc(db, "tabs", name));
  if (!baseSnap.exists()) return [];

  const baseData = baseSnap.data() as {
    rows?: Record<string, unknown>[];
    chunks?: number;
  };
  const rows: Record<string, unknown>[] = Array.isArray(baseData.rows)
    ? [...baseData.rows]
    : [];

  const chunks = Number(baseData.chunks) || 0;
  if (chunks > 0) {
    // Fetch the numbered chunks in parallel, then splice them in by index so
    // row order is preserved regardless of network completion order.
    const chunkSnaps = await Promise.all(
      Array.from({ length: chunks }, (_, i) =>
        getDoc(doc(db, "tabs", `${name}__${i + 1}`)),
      ),
    );
    for (const snap of chunkSnaps) {
      if (!snap.exists()) continue;
      const part = snap.data() as { rows?: Record<string, unknown>[] };
      if (Array.isArray(part.rows)) rows.push(...part.rows);
    }
  }

  return rows.map(coerceRowToStrings) as T[];
}

/**
 * Write one decision (fill / kill / defer) to the client-writable `decisions`
 * collection. This is the PWA side of the decision write-back: the backend
 * (signal_feedback) reads this collection via the Admin SDK to grade the user's
 * ACTUAL choices, closing the feedback loop that previously lived only in
 * localStorage.
 *
 * Security: `decisions` is the ONLY client-writable surface (see firestore.rules
 * — read+write gated on the same two-email allowlist as the read-only `tabs`).
 * `merge: true` so a later re-record of the same key updates in place rather
 * than clobbering. We stamp `updatedAt` (server clock — authoritative ordering)
 * and `user` (who recorded it) on top of whatever the caller passes.
 *
 * The doc id is the decision key (date|account|ticker|strategy|strike — the same
 * compound key `decisionActions.keyForDecision` / the backend `decision_key`
 * produce), so a decision is addressable from either side.
 */
export async function writeDecision(key: string, data: object): Promise<void> {
  await setDoc(
    doc(db, "decisions", key),
    {
      ...data,
      updatedAt: serverTimestamp(),
      user: auth.currentUser?.email ?? null,
    },
    { merge: true },
  );
}
