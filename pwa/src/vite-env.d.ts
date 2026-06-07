/// <reference types="vite/client" />

/**
 * Typed environment variables for the private read path.
 *
 * - VITE_DATA_SOURCE flips the data transport. 'gviz' (default) reads the
 *   public Google Sheet CSV; 'firestore' reads the private Firestore mirror
 *   behind Google sign-in. Anything other than 'firestore' is treated as gviz
 *   so the existing public path keeps working until cutover.
 * - The six VITE_FIREBASE_* values are the Firebase WEB config. They are
 *   public-safe by design (security is Auth + Firestore rules, not secrecy),
 *   but are still read from env so no real project values are committed.
 */
interface ImportMetaEnv {
  readonly VITE_DATA_SOURCE?: "gviz" | "firestore";
  readonly VITE_FIREBASE_API_KEY?: string;
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string;
  readonly VITE_FIREBASE_PROJECT_ID?: string;
  readonly VITE_FIREBASE_STORAGE_BUCKET?: string;
  readonly VITE_FIREBASE_MESSAGING_SENDER_ID?: string;
  readonly VITE_FIREBASE_APP_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
