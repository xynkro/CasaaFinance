/**
 * Firebase auth gate (firestore mode only).
 *
 * App.tsx loads this lazily (React.lazy) when VITE_DATA_SOURCE==='firestore',
 * so the Firebase SDK and config-init in lib/firebase.ts are only pulled in
 * on the private path. The default gviz path never imports this file.
 *
 * Gate states:
 *   - resolving auth   → LoadingState
 *   - signed out       → <SignInScreen>
 *   - sign-in error    → <SignInScreen error=...>
 *   - signed in        → children (the dashboard). Allowlist enforcement is
 *     server-side via Firestore rules; if a non-allowlisted user signs in,
 *     their tab reads fail and the dashboard surfaces the load error /
 *     NotAuthorized state from there. We still expose onSignOut so they can
 *     switch accounts.
 */
import { useEffect, useState } from "react";
import type { User } from "firebase/auth";
import { onUser, signInWithGoogle, signOutUser } from "./lib/firebase";
import { LoadingState, SignInScreen } from "./components/AsyncStates";

export default function FirebaseGate({
  children,
}: {
  children: (ctx: { user: User; signOut: () => void }) => React.ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [resolving, setResolving] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const unsub = onUser((u) => {
      setUser(u);
      setResolving(false);
    });
    return unsub;
  }, []);

  const handleSignIn = () => {
    setBusy(true);
    setError(null);
    signInWithGoogle()
      .catch((e: unknown) => {
        // Don't surface a scary error for the user simply closing the popup.
        const code = (e as { code?: string })?.code ?? "";
        if (code !== "auth/popup-closed-by-user" && code !== "auth/cancelled-popup-request") {
          setError("Sign-in failed. Please try again.");
        }
      })
      .finally(() => setBusy(false));
  };

  const handleSignOut = () => {
    void signOutUser();
  };

  if (resolving) {
    return (
      <div className="h-screen flex flex-col items-center justify-center relative">
        <div className="bg-layer" aria-hidden="true" />
        <div className="w-full max-w-sm">
          <LoadingState rows={2} label="Checking sign-in…" />
        </div>
      </div>
    );
  }

  if (!user) {
    return <SignInScreen onSignIn={handleSignIn} busy={busy} error={error} />;
  }

  return <>{children({ user, signOut: handleSignOut })}</>;
}
