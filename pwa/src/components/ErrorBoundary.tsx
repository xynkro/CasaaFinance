import { Component, type ReactNode } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";

/**
 * Catches render/runtime errors in the page subtree so ONE broken screen shows
 * a recoverable message instead of white-screening the whole app (which also
 * kills the tab bar and navigation — the failure mode that made the Options
 * hooks crash so painful). Wrapped per-tab in App.tsx and keyed by tab, so
 * switching tabs auto-recovers.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string }) {
    // Surface for debugging — never silently swallow.
    console.error("ErrorBoundary caught:", error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center text-center gap-3 px-6 py-16 fade-up">
          <div className="w-12 h-12 rounded-2xl flex items-center justify-center bg-amber-500/15 text-amber-400">
            <AlertTriangle size={22} aria-hidden="true" />
          </div>
          <div className="max-w-xs">
            <h2 className="text-[length:var(--t-base)] font-semibold text-slate-100">
              This screen hit an error
            </h2>
            <p className="text-[length:var(--t-xs)] text-slate-400 mt-1 leading-relaxed break-words">
              {this.state.error.message || "Something went wrong rendering this page."}
            </p>
            <p className="text-[length:var(--t-2xs)] text-slate-600 mt-2">
              Other tabs still work — switch away and back, or reload.
            </p>
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-[length:var(--t-sm)] font-medium text-slate-100 transition-all active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
            style={{ background: "var(--surface-bright)", border: "1px solid var(--border-bright)" }}
          >
            <RotateCw size={15} aria-hidden="true" /> Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
