import { useEffect, useRef, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
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
import { RefreshCw } from "lucide-react";

const TAB_TITLES = ["Home", "Portfolio", "Options", "Decisions", "Archive", "Settings"];
const SETTINGS_TAB = 5;

function Dashboard() {
  const { settings, update: updateSettings } = useSettings();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState(settings.defaultTab);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = () => {
    setLoading(true);
    return fetchDashboard().then((d) => {
      setData(d);
      setLoading(false);
    });
  };

  useEffect(() => { load(); }, []);

  // Scroll to top when switching tabs
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
            recommendations={data?.optionRecommendations ?? []}
            technicalScores={data?.technicalScores ?? []}
            wheelNextLeg={data?.wheelNextLeg ?? []}
            scanResults={data?.scanResults ?? []}
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

      {/* Fixed header */}
      <header className="app-header">
        <div className="flex items-center justify-between py-3 px-4">
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight">{TAB_TITLES[tab]}</h1>
            <p className="text-[10px] text-slate-400 mt-0.5">Casaa Finance</p>
          </div>
          {tab !== SETTINGS_TAB && (
            <button
              onClick={() => load()}
              disabled={loading}
              className="p-2.5 rounded-xl glass text-slate-300 hover:text-white active:scale-95 transition-all disabled:opacity-40"
              aria-label="Refresh"
            >
              <RefreshCw size={16} className={loading ? "spin-smooth" : ""} />
            </button>
          )}
        </div>
      </header>

      {/* Scrollable content — with pull-to-refresh */}
      <main ref={scrollRef} className="app-content">
        <PullToRefresh onRefresh={load} scrollRef={scrollRef}>
          {data?.error && (
            <div className="mx-4 mb-4 rounded-xl glass border-red-500/30 p-3 text-sm text-red-300 fade-up">
              {data.error}
            </div>
          )}
          {renderPage()}
        </PullToRefresh>
      </main>

      {/* Fixed bottom tab bar */}
      <TabBar
        active={tab}
        onChange={setTab}
        decisionCount={pendingCount}
        defenseAlerts={urgentDefense}
      />
    </div>
  );
}

export default function App() {
  const { authed, grant } = usePinAuth();
  if (!authed) return <PinGate onSuccess={grant} />;
  return <Dashboard />;
}
