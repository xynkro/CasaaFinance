import { useEffect, useRef, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
import type { TechnicalScoreRow } from "./data";
import { PinGate, usePinAuth } from "./PinGate";
import { useSettings } from "./settings";
import { TabBar } from "./components/TabBar";
import { PullToRefresh } from "./components/PullToRefresh";
import { HomePage } from "./pages/HomePage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { OptionsPage } from "./pages/OptionsPage";
import { DecisionsPage } from "./pages/DecisionsPage";
import { ArchivePage } from "./pages/ArchivePage";
import { SettingsPage } from "./pages/SettingsPage";
import { StockDetail } from "./components/StockDetail";
import { TickerLookupSheet } from "./components/TickerLookupSheet";
import { RefreshCw, Search } from "lucide-react";

const TAB_TITLES = ["Home", "Portfolio", "Options", "Decisions", "Archive", "Settings"];
const SETTINGS_TAB = 5;

function Dashboard() {
  const { settings, update: updateSettings } = useSettings();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
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
    });
  };

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [tab]);

  const handleLogout = () => {
    localStorage.removeItem("casaa_pin_ok");
    window.location.reload();
  };

  const pendingCount = (data?.decisions ?? []).filter(
    (d) => d.status?.toLowerCase() === "pending" || d.status?.toLowerCase() === "watching",
  ).length;

  const urgentDefense = (data?.optionsDefense ?? []).filter(
    (d) => d.severity === "CRITICAL" || d.severity === "HIGH",
  ).length;

  const renderPage = () => {
    switch (tab) {
      case 0:
        return <HomePage data={data} loading={loading} />;
      case 1:
        return (
          <PortfolioPage
            casparSnapshot={data?.caspar ?? null}
            casparPositions={data?.casparPositions ?? []}
            sarahSnapshot={data?.sarah ?? null}
            sarahPositions={data?.sarahPositions ?? []}
            casparHistory={data?.casparHistory ?? []}
            sarahHistory={data?.sarahHistory ?? []}
            macroHistory={data?.macroHistory ?? []}
            technicalScores={data?.technicalScores ?? []}
            technicalScoresHistory={data?.technicalScoresHistory ?? []}
            exitPlans={data?.exitPlans ?? []}
            loading={loading && !data}
          />
        );
      case 2:
        return (
          <OptionsPage
            options={data?.options ?? []}
            technicalScores={data?.technicalScores ?? []}
            wheelNextLeg={data?.wheelNextLeg ?? []}
            scanResults={data?.scanResults ?? []}
            optionRecommendations={data?.optionRecommendations ?? []}
            exitPlans={data?.exitPlans ?? []}
            optionsDefense={data?.optionsDefense ?? []}
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            loading={loading && !data}
          />
        );
      case 3:
        return (
          <DecisionsPage
            decisions={data?.decisions ?? []}
            technicalScores={data?.technicalScores ?? []}
            technicalScoresHistory={data?.technicalScoresHistory ?? []}
          />
        );
      case 4:
        return <ArchivePage archive={data?.archive ?? []} dailyHistory={data?.dailyHistory ?? []} />;
      case 5:
        return <SettingsPage settings={settings} onUpdate={updateSettings} onLogout={handleLogout} />;
      default:
        return null;
    }
  };

  return (
    <div className="app-shell">
      <div className="bg-layer" />

      {/* Header */}
      <header className="app-header">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-baseline gap-2.5">
            <h1 className="text-[length:var(--t-lg)] font-semibold tracking-[-0.02em] text-white leading-none">
              {TAB_TITLES[tab]}
            </h1>
            <span className="text-[length:var(--t-xs)] text-slate-500 font-medium">Casaa Finance</span>
            <span className="text-[8px] text-slate-700 font-mono">b{import.meta.env.VITE_BUILD ?? "dev"}</span>
          </div>
          {tab !== SETTINGS_TAB && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => setLookupOpen(true)}
                className="flex items-center justify-center w-9 h-9 rounded-xl transition-all active:scale-90"
                style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
                aria-label="Analyse ticker"
              >
                <Search size={15} style={{ color: "rgb(148 163 184)" }} />
              </button>
              <button
                onClick={() => load()}
                disabled={loading}
                className="flex items-center justify-center w-9 h-9 rounded-xl transition-all disabled:opacity-30 active:scale-90"
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
          {renderPage()}
        </PullToRefresh>
      </main>

      <TabBar
        active={tab}
        onChange={setTab}
        decisionCount={pendingCount}
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

export default function App() {
  const { authed, grant } = usePinAuth();
  if (!authed) return <PinGate onSuccess={grant} />;
  return <Dashboard />;
}
