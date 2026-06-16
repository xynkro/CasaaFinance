import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
import { evaluateTrigger } from "./data/normalize";
import type { TechnicalScoreRow } from "./data";
import { PinGate } from "./PinGate";
import { usePinAuth } from "./lib/usePinAuth";
import { useSettings } from "./settings";
import { LoadingState, ErrorState, NotAuthorized } from "./components/AsyncStates";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { TabBar } from "./components/TabBar";
import { PullToRefresh } from "./components/PullToRefresh";
import { HomePage } from "./pages/HomePage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { OptionsPage } from "./pages/OptionsPage";
import { ScannerPage } from "./pages/ScannerPage";
import { InsiderPage } from "./pages/InsiderPage";
import { DecisionsPage } from "./pages/DecisionsPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StockDetail } from "./components/StockDetail";
import { TickerLookupSheet } from "./components/TickerLookupSheet";
import { RefreshCw, Search } from "lucide-react";

const TAB_TITLES = ["Home", "Portfolio", "Options", "Scanner", "Insider", "Decisions", "Review", "Settings"];
const SETTINGS_TAB = 7;

/** Named tab indices — import these instead of hardcoding numbers. A literal
 *  `onJumpTab?.(3)` in HomePage silently routed every urgent ACT-NOW tile to
 *  the Scanner page after the tab order changed (Decisions moved 3→5). */
export const TAB = {
  HOME: 0, PORTFOLIO: 1, OPTIONS: 2, SCANNER: 3,
  INSIDER: 4, DECISIONS: 5, REVIEW: 6, SETTINGS: 7,
} as const;

// Private read path: when VITE_DATA_SOURCE==='firestore', the dashboard sits
// behind Google sign-in instead of the localStorage PIN. The gate component
// is lazy-loaded so the Firebase SDK is only pulled in on the private path.
const USE_FIRESTORE = import.meta.env.VITE_DATA_SOURCE === "firestore";
const FirebaseGate = lazy(() => import("./FirebaseGate"));

/** Detect a Firestore permission denial — the signal that a signed-in user
 *  isn't on the allowlist (rules deny the read). */
function isPermissionError(msg: string | null | undefined): boolean {
  if (!msg) return false;
  return /permission-denied|insufficient permissions|missing or insufficient/i.test(msg);
}

/** Auth context handed down from the Firestore gate (null in PIN/gviz mode). */
type AuthCtx = { email: string | null; signOut: () => void } | null;

function Dashboard({ authCtx }: { authCtx?: AuthCtx }) {
  const { settings, update: updateSettings } = useSettings();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [tab, setTab] = useState(settings.defaultTab);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [lookupOpen, setLookupOpen] = useState(false);
  const [lookupTicker, setLookupTicker] = useState<string | null>(null);
  const [lookupTechScore, setLookupTechScore] = useState<TechnicalScoreRow | undefined>();

  const load = () => {
    setLoading(true);
    return fetchDashboard().then((d) => {
      setData(d);
      setLoading(false);
      setLastRefresh(new Date());
    });
  };

  // Fetch on mount. setState-in-effect is the canonical pattern for
  // "load when component mounts", and React's docs explicitly call it out
  // as fine for external-system sync (network → state).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, []);

  // Auto-refresh: every 15 min + whenever the app comes back to foreground
  useEffect(() => {
    const INTERVAL_MS = 15 * 60 * 1000;
    const timer = setInterval(() => { load(); }, INTERVAL_MS);

    const onVisibility = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [tab]);

  const handleLogout = () => {
    // Firestore mode: sign out of Firebase (auth-state change re-renders the
    // gate to the sign-in screen). PIN/gviz mode: clear the PIN session.
    if (authCtx) {
      authCtx.signOut();
      return;
    }
    localStorage.removeItem("casaa_pin_ok");
    window.location.reload();
  };

  // A hard failure with no usable data yet (the in-component fetchDashboard
  // catch surfaces errors via data.error while returning empty collections).
  const loadFailed = !loading && data?.error != null;
  // Firestore + permission denial == signed in but not on the allowlist.
  const notAuthorized = USE_FIRESTORE && loadFailed && isPermissionError(data?.error);

  // Badge counts WHAT NEEDS ACTION, not the backlog. The old pending+watching
  // count produced a permanent 6-8 (watching is explicitly do-nothing) that
  // trained the eye to ignore it. Now: pending (needs accept) + watching rows
  // whose live trigger evaluates ready/act_now — and the badge turns red when
  // anything is act_now.
  const decisionBadge = useMemo(() => {
    let urgent = 0, count = 0;
    for (const d of data?.decisions ?? []) {
      const status = (d.status || "").toLowerCase();
      if (status === "pending") { count += 1; continue; }
      if (status !== "watching") continue;
      const tk = (d.ticker || "").toUpperCase();
      const ev = evaluateTrigger(
        d,
        Number(data?.livePrices?.get(tk)?.last) || undefined,
        data?.exposurePosture ?? null,
        data?.tvSignals?.get(tk),
      );
      if (ev.state === "act_now") { urgent += 1; count += 1; }
      else if (ev.state === "ready") count += 1;
    }
    return { count, urgent };
  }, [data]);
  const pendingCount = decisionBadge.count;

  const urgentDefense = (data?.optionsDefense ?? []).filter(
    (d) => d.severity === "CRITICAL" || d.severity === "HIGH",
  ).length;

  const renderPage = () => {
    switch (tab) {
      case 0:
        return <HomePage data={data} loading={loading} onJumpTab={setTab} />;
      case 1:
        return (
          <PortfolioPage
            casparSnapshot={data?.caspar ?? null}
            casparPositions={data?.casparPositions ?? []}
            sarahSnapshot={data?.sarah ?? null}
            sarahPositions={data?.sarahPositions ?? []}
            technicalScores={data?.technicalScores ?? []}
            technicalScoresHistory={data?.technicalScoresHistory ?? []}
            exitPlans={data?.exitPlans ?? []}
            livePrices={data?.livePrices ?? new Map()}
            livePricesUpdatedAt={data?.livePricesUpdatedAt ?? ""}
            usdSgd={Number(data?.macro?.usd_sgd) || 1.30}
            alpacaSnapshot={data?.alpaca ?? null}
            alpacaPositions={data?.alpacaPositions ?? []}
            paperBenchmark={data?.paperBenchmark ?? []}
            dailyPlan={data?.dailyPlan ?? []}
            loading={loading && !data}
          />
        );
      case 2:
        return (
          <OptionsPage
            options={data?.options ?? []}
            technicalScores={data?.technicalScores ?? []}
            wheelNextLeg={data?.wheelNextLeg ?? []}
            exitPlans={data?.exitPlans ?? []}
            optionsDefense={data?.optionsDefense ?? []}
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            harvestScan={data?.harvestScan ?? []}
            scanResults={data?.scanResults ?? []}
            uoaAlerts={data?.uoaAlerts ?? []}
            gexRegime={data?.gexRegime ?? []}
            macroLean={data?.macroLean ?? null}
            scanMeta={data?.scanMeta ?? null}
            exposurePosture={data?.exposurePosture ?? null}
            mfOverlay={data?.mfOverlay ?? []}
            loading={loading && !data}
          />
        );
      case 3:
        return (
          <ScannerPage
            ivSurfaceScan={data?.ivSurfaceScan ?? []}
            loading={loading && !data}
            exposurePosture={data?.exposurePosture ?? null}
            gexRegime={data?.gexRegime ?? null}
            scanMeta={data?.scanMeta ?? null}
          />
        );
      case 4:
        return (
          <InsiderPage
            govConfluence={data?.govConfluence ?? []}
            congressTrades={data?.congressTrades ?? []}
            insiderByTicker={data?.insiderByTicker ?? new Map()}
            loading={loading && !data}
          />
        );
      case 5:
        return (
          <DecisionsPage
            decisions={data?.decisions ?? []}
            technicalScores={data?.technicalScores ?? []}
            technicalScoresHistory={data?.technicalScoresHistory ?? []}
            optionsDefense={data?.optionsDefense ?? []}
            wheelNextLeg={data?.wheelNextLeg ?? []}
            exitPlans={data?.exitPlans ?? []}
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            exposurePosture={data?.exposurePosture ?? null}
            gexRegime={data?.gexRegime ?? null}
            scanMeta={data?.scanMeta ?? null}
            casparSnapshot={data?.caspar ?? null}
            sarahSnapshot={data?.sarah ?? null}
            tvSignals={data?.tvSignals}
            earnings={data?.earnings ?? []}
            analystByTicker={data?.analystByTicker}
            newsByTicker={data?.newsByTicker}
            insiderByTicker={data?.insiderByTicker}
            screenCandidates={data?.screenCandidates ?? []}
            livePrices={data?.livePrices ?? new Map()}
            dailyPlan={data?.dailyPlan ?? []}
            mfWatchlist={data?.mfWatchlist ?? []}
          />
        );
      case 6:
        return (
          <ReviewPage
            decisionsAll={data?.decisionsAll ?? []}
            casparHistory={data?.casparHistory ?? []}
            sarahHistory={data?.sarahHistory ?? []}
            macroHistory={data?.macroHistory ?? []}
            archive={data?.archive ?? []}
            dailyHistory={data?.dailyHistory ?? []}
            riskParityAudit={data?.riskParityAudit ?? []}
            livePrices={data?.livePrices ?? new Map()}
          />
        );
      case 7:
        return (
          <SettingsPage
            settings={settings}
            onUpdate={updateSettings}
            onLogout={handleLogout}
            apiUsage={data?.apiUsage ?? []}
            authMode={authCtx ? "firestore" : "pin"}
            userEmail={authCtx?.email ?? null}
          />
        );
      default:
        return null;
    }
  };

  // Signed in but not allowlisted (Firestore rules denied the read).
  if (notAuthorized) {
    return <NotAuthorized email={authCtx?.email} onSignOut={authCtx?.signOut} />;
  }

  // First load failed with no usable data — full-screen error + retry. Once
  // data has loaded at least once, a later refresh error shows the inline
  // banner instead (handled below) so the user keeps the last-good view.
  if (loadFailed && lastRefresh === null) {
    return (
      <div className="app-shell">
        <div className="bg-layer" />
        <main className="app-content flex items-center justify-center">
          <ErrorState message={data?.error ?? undefined} onRetry={load} />
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="bg-layer" />

      {/* Header */}
      <header className="app-header">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5 min-w-0">
            {/* App logo mark — small + tasteful, ties the running app to the
                sign-in gate brand. Decorative (the title carries the label). */}
            <img
              src={`${import.meta.env.BASE_URL}icon-192.png`}
              alt=""
              aria-hidden="true"
              className="w-[22px] h-[22px] rounded-[7px] shrink-0 ring-1 ring-white/10 shadow-sm shadow-black/40"
            />
            <div className="flex items-baseline gap-2.5 min-w-0">
              <h1 className="text-[length:var(--t-lg)] font-semibold tracking-[-0.02em] text-white leading-none">
                {TAB_TITLES[tab]}
              </h1>
              <span className="text-[length:var(--t-xs)] text-slate-500 font-medium">Casaa Finance</span>
              <span className="text-[8px] text-slate-700 font-mono">b{import.meta.env.VITE_BUILD ?? "dev"}</span>
              {lastRefresh && (
                <span className="text-[8px] text-slate-700 font-mono">
                  {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
            </div>
          </div>
          {tab !== SETTINGS_TAB && (
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => setLookupOpen(true)}
                className="relative flex items-center justify-center w-9 h-9 rounded-xl transition-[transform,border-color] active:scale-90 focusable before:absolute before:-inset-1"
                style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
                aria-label="Analyse ticker"
              >
                <Search size={15} style={{ color: "rgb(148 163 184)" }} />
              </button>
              <button
                onClick={() => load()}
                disabled={loading}
                className="relative flex items-center justify-center w-9 h-9 rounded-xl transition-[transform,border-color] disabled:opacity-30 active:scale-90 focusable before:absolute before:-inset-1"
                style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
                aria-label="Refresh"
              >
                <RefreshCw
                  size={15}
                  className={loading ? "spin-smooth" : ""}
                  style={{ color: "rgb(148 163 184)" }}
                />
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Scrollable content */}
      <main ref={scrollRef} className="app-content">
        <PullToRefresh onRefresh={load} scrollRef={scrollRef}>
          {data?.error && (
            <div className="mx-4 mb-3 rounded-xl p-3 text-[length:var(--t-sm)] text-red-300 fade-up"
                 style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)" }}>
              {data.error}
            </div>
          )}
          {/* Keyed by tab so each switch re-fires the page-enter keyframe —
              gives the whole-page swap a smooth settle instead of a hard cut.
              The in-page fade-up cards still cascade on top. Reduced-motion
              strips the animation (see index.css). */}
          <div key={tab} className="page-enter">
            {/* Per-tab boundary: a crash in one page shows a recoverable
                message instead of white-screening the app + killing the tab
                bar. Keyed by `tab` (parent div), so it resets on navigation. */}
            <ErrorBoundary>{renderPage()}</ErrorBoundary>
          </div>
        </PullToRefresh>
      </main>

      <TabBar
        active={tab}
        onChange={setTab}
        decisionCount={pendingCount}
        decisionUrgent={decisionBadge.urgent > 0}
        defenseAlerts={urgentDefense}
      />

      {/* Global ticker lookup */}
      <TickerLookupSheet
        open={lookupOpen}
        onClose={() => setLookupOpen(false)}
        technicalScores={data?.technicalScores ?? []}
        onSelect={(ticker, techScore) => {
          setLookupTicker(ticker);
          setLookupTechScore(techScore);
        }}
      />
      {lookupTicker && (
        <StockDetail
          ticker={lookupTicker}
          techScore={lookupTechScore}
          techHistory={data?.technicalScoresHistory}
          currency="USD"
          onClose={() => { setLookupTicker(null); setLookupTechScore(undefined); }}
        />
      )}
    </div>
  );
}

/** PIN-gated app (gviz / dev path) — unchanged from before the private read path. */
function PinGatedApp() {
  const { authed, grant } = usePinAuth();
  if (!authed) return <PinGate onSuccess={grant} />;
  return <Dashboard />;
}

/** Shown when the lazy FirebaseGate chunk can't load even after an auto-reload
 *  (genuinely-missing chunk / offline). Without this, the Suspense fallback
 *  below would spin forever — the "stuck loading, no data" report. */
function GateLoadError() {
  return (
    <div className="h-screen flex flex-col items-center justify-center text-center gap-4 px-6 relative">
      <div className="bg-layer" aria-hidden="true" />
      <div className="relative max-w-xs flex flex-col items-center gap-3">
        <RefreshCw size={26} className="text-sky-400" aria-hidden="true" />
        <h2 className="text-[length:var(--t-base)] font-semibold text-slate-100">
          Couldn’t finish loading
        </h2>
        <p className="text-[length:var(--t-xs)] text-slate-400 leading-relaxed">
          A new version was deployed. Tap reload to pull it — your data is safe.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="mt-1 flex items-center gap-2 px-5 py-2.5 rounded-xl text-[length:var(--t-sm)] font-semibold text-slate-100 active:scale-[0.98]"
          style={{ background: "var(--surface-bright)", border: "1px solid var(--border-bright)" }}
        >
          <RefreshCw size={15} aria-hidden="true" /> Reload
        </button>
      </div>
    </div>
  );
}

/** Google-sign-in-gated app (firestore path). */
function FirestoreGatedApp() {
  return (
    <ErrorBoundary fallback={<GateLoadError />}>
      <Suspense
        fallback={
          <div className="h-screen flex flex-col items-center justify-center relative">
            <div className="bg-layer" aria-hidden="true" />
            <div className="w-full max-w-sm">
              <LoadingState rows={2} label="Loading…" />
            </div>
          </div>
        }
      >
        <FirebaseGate>
          {({ user, signOut }) => (
            <Dashboard authCtx={{ email: user.email, signOut }} />
          )}
        </FirebaseGate>
      </Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return USE_FIRESTORE ? <FirestoreGatedApp /> : <PinGatedApp />;
}
