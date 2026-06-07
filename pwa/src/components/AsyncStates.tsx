/**
 * Reusable async-state components for the private read path (and beyond).
 *
 * These are the shared building blocks for every "the data isn't ready" UI:
 * loading skeletons, empty tabs, load errors with retry, the not-authorised
 * screen, and the Google sign-in screen. They use the app's existing theme
 * tokens (--t-* type scale, .glass / .glass-bright surfaces, .bg-layer,
 * .shimmer, .fade-up) and follow accessibility basics: status regions are
 * announced via role + aria-live, decorative chrome is aria-hidden, and every
 * action is a real keyboard-focusable <button>.
 */
import { AlertTriangle, RefreshCw, Inbox, ShieldX, LogIn } from "lucide-react";

/* ─── LoadingState ─────────────────────────────────────────────────────────
   Shimmer skeleton standing in for content that's still loading. Marked
   aria-busy + role="status" so assistive tech announces "loading" and the
   visual skeleton itself is hidden from the a11y tree. */
export function LoadingState({
  rows = 4,
  label = "Loading…",
  className = "",
}: {
  /** Number of skeleton blocks to render. */
  rows?: number;
  /** Screen-reader label announced while busy. */
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className={`flex flex-col gap-3 px-4 py-3 ${className}`}
    >
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="glass rounded-2xl p-4 fade-up"
          style={{ animationDelay: `${i * 0.05}s` }}
        >
          <div className="shimmer h-3 w-1/3 mb-3" />
          <div className="shimmer h-6 w-2/3 mb-2" />
          <div className="shimmer h-3 w-full mb-1.5" />
          <div className="shimmer h-3 w-4/5" />
        </div>
      ))}
    </div>
  );
}

/* ─── EmptyState ───────────────────────────────────────────────────────────
   Neutral "nothing here yet" panel. Not an error — used when a tab is
   legitimately empty (e.g. no decisions today). */
export function EmptyState({
  title,
  message,
  icon: Icon = Inbox,
  className = "",
}: {
  title: string;
  message?: string;
  icon?: React.ComponentType<{ size?: number; className?: string }>;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex flex-col items-center justify-center text-center gap-3 px-6 py-12 fade-up ${className}`}
    >
      <div
        aria-hidden="true"
        className="w-14 h-14 rounded-2xl flex items-center justify-center"
        style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
      >
        <Icon size={24} className="text-slate-500" />
      </div>
      <div className="max-w-xs">
        <h2 className="text-[length:var(--t-base)] font-semibold text-slate-200">{title}</h2>
        {message && (
          <p className="text-[length:var(--t-sm)] text-slate-400 mt-1 leading-relaxed">{message}</p>
        )}
      </div>
    </div>
  );
}

/* ─── ErrorState ───────────────────────────────────────────────────────────
   Load failure with an optional retry. role="alert" so it's announced
   assertively the moment it appears. */
export function ErrorState({
  message = "Something went wrong while loading.",
  onRetry,
  title = "Couldn't load data",
  className = "",
}: {
  message?: string;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`flex flex-col items-center justify-center text-center gap-4 px-6 py-12 fade-up ${className}`}
    >
      <div
        aria-hidden="true"
        className="w-14 h-14 rounded-2xl flex items-center justify-center"
        style={{ background: "rgba(248,113,113,0.10)", border: "1px solid rgba(248,113,113,0.22)" }}
      >
        <AlertTriangle size={24} className="text-red-400" />
      </div>
      <div className="max-w-sm">
        <h2 className="text-[length:var(--t-base)] font-semibold text-slate-100">{title}</h2>
        <p className="text-[length:var(--t-sm)] text-slate-400 mt-1 leading-relaxed break-words">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-[length:var(--t-sm)] text-slate-100 transition-all active:scale-95 hover:border-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
          style={{ background: "var(--surface-bright)", border: "1px solid var(--border-bright)" }}
        >
          <RefreshCw size={15} aria-hidden="true" />
          Retry
        </button>
      )}
    </div>
  );
}

/* ─── Full-screen shell ────────────────────────────────────────────────────
   Shared centred container for the two full-page gates (NotAuthorized,
   SignInScreen). Mirrors PinGate's layout (bg-layer + centred glass card). */
function FullScreenShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen flex flex-col items-center justify-center px-6 relative">
      <div className="bg-layer" aria-hidden="true" />
      {children}
    </div>
  );
}

/* ─── NotAuthorized ────────────────────────────────────────────────────────
   Signed in, but not on the allowlist (Firestore rules also deny the read).
   Offers a sign-out so the user can retry with a different Google account. */
export function NotAuthorized({
  email,
  onSignOut,
}: {
  /** The signed-in email that isn't allowlisted (shown so the user knows which account to switch from). */
  email?: string | null;
  onSignOut?: () => void;
}) {
  return (
    <FullScreenShell>
      <div
        role="alert"
        aria-live="assertive"
        className="glass-bright rounded-3xl p-8 w-full max-w-sm flex flex-col items-center gap-5 text-center fade-up"
      >
        <div
          aria-hidden="true"
          className="w-16 h-16 rounded-2xl flex items-center justify-center bg-red-500/15 text-red-400"
        >
          <ShieldX size={28} />
        </div>
        <div>
          <h1 className="text-[length:var(--t-xl)] font-bold text-slate-100 mb-1">Not authorized</h1>
          <p className="text-[length:var(--t-sm)] text-slate-400 leading-relaxed">
            This account doesn't have access to Casaa Finance.
          </p>
          {email && (
            <p className="text-[length:var(--t-xs)] text-slate-500 mt-2 font-mono break-all">{email}</p>
          )}
        </div>
        {onSignOut && (
          <button
            onClick={onSignOut}
            className="w-full py-3 rounded-xl font-medium text-[length:var(--t-sm)] text-slate-100 transition-all active:scale-[0.98] hover:border-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
            style={{ background: "var(--surface-bright)", border: "1px solid var(--border-bright)" }}
          >
            Use a different account
          </button>
        )}
      </div>
    </FullScreenShell>
  );
}

/* ─── SignInScreen ─────────────────────────────────────────────────────────
   Signed-out gate. Single Google sign-in button. Surfaces an optional error
   (e.g. popup blocked / cancelled) and a busy state while the popup is open. */
export function SignInScreen({
  onSignIn,
  busy = false,
  error,
}: {
  onSignIn: () => void;
  /** True while the sign-in popup is open / resolving. */
  busy?: boolean;
  /** Optional error message from a failed sign-in attempt. */
  error?: string | null;
}) {
  return (
    <FullScreenShell>
      <div className="glass-bright rounded-3xl p-8 w-full max-w-sm flex flex-col items-center gap-6 fade-up">
        <div
          aria-hidden="true"
          className="w-16 h-16 rounded-2xl flex items-center justify-center bg-indigo-500/15 text-indigo-400"
        >
          <LogIn size={28} />
        </div>

        <div className="text-center">
          <h1 className="text-[length:var(--t-xl)] font-bold text-slate-100 mb-1">Casaa Finance</h1>
          <p className="text-[length:var(--t-sm)] text-slate-400">Sign in to continue</p>
        </div>

        <button
          onClick={onSignIn}
          disabled={busy}
          aria-busy={busy}
          className="w-full flex items-center justify-center gap-3 py-3 rounded-xl font-semibold text-[length:var(--t-sm)] bg-white text-slate-800 transition-all active:scale-[0.98] disabled:opacity-60 disabled:active:scale-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
        >
          {busy ? (
            <>
              <RefreshCw size={18} className="spin-smooth" aria-hidden="true" />
              Signing in…
            </>
          ) : (
            <>
              <GoogleIcon />
              Continue with Google
            </>
          )}
        </button>

        {error && (
          <p role="alert" aria-live="assertive" className="text-[length:var(--t-sm)] text-red-400 font-medium text-center">
            {error}
          </p>
        )}
      </div>
    </FullScreenShell>
  );
}

/** Google "G" mark, inlined so the sign-in button needs no asset/network. */
function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"
      />
    </svg>
  );
}
