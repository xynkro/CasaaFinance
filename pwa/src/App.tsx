import { useEffect, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
import { PinGate, usePinAuth } from "./PinGate";
import { useSettings } from "./settings";
import { TabBar } from "./components/TabBar";
import { HomePage } from "./pages/HomePage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { OptionsPage } from "./pages/OptionsPage";
import { DecisionsPage } from "./pages/DecisionsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { ArchivePage } from "./pages/ArchivePage";
import { SettingsPage } from "./pages/SettingsPage";
import { RefreshCw } from "lucide-react";

const TAB_TITLES = ["Home", "Caspar", "Sarah", "Options", "Decisions", "History", "Archive", "Settings"];
const SETTINGS_TAB = 7;

function Dashboard() {
  const { settings, update: updateSettings } = useSettings();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState(settings.defaultTab);

  const load = () => {
    setLoading(true);
    fetchDashboard().then((d) => {
      setData(d);
      setLoading(false);
    });
  };

  useEffect(load, []);

  const handleLogout = () => {
    localStorage.removeItem("casaa_pin_ok");
    window.location.reload();
  };

  const pendingCount = (data?.decisions ?? []).filter(
    (d) => d.status?.toLowerCase() === "pending" || d.status?.toLowerCase() === "watching",
  ).length;

  const renderPage = () => {
    switch (tab) {
      case 0: return <HomePage data={data} loading={loading} />;
      case 1: return <PortfolioPage label="Caspar" currency="USD" account="caspar" snapshot={data?.caspar ?? null} positions={data?.casparPositions ?? []} technicalScores={data?.technicalScores ?? []} technicalScoresHistory={data?.technicalScoresHistory ?? []} exitPlans={data?.exitPlans ?? []} loading={loading && !data} />;
      case 2: return <PortfolioPage label="Sarah" currency="SGD" account="sarah" snapshot={data?.sarah ?? null} positions={data?.sarahPositions ?? []} technicalScores={data?.technicalScores ?? []} technicalScoresHistory={data?.technicalScoresHistory ?? []} exitPlans={data?.exitPlans ?? []} loading={loading && !data} />;
      case 3: return <OptionsPage options={data?.options ?? []} recommendations={data?.optionRecommendations ?? []} technicalScores={data?.technicalScores ?? []} wheelNextLeg={data?.wheelNextLeg ?? []} scanResults={data?.scanResults ?? []} exitPlans={data?.exitPlans ?? []} casparPositions={data?.casparPositions ?? []} sarahPositions={data?.sarahPositions ?? []} loading={loading && !data} />;
      case 4: return <DecisionsPage decisions={data?.decisions ?? []} technicalScores={data?.technicalScores ?? []} technicalScoresHistory={data?.technicalScoresHistory ?? []} />;
      case 5: return <HistoryPage casparHistory={data?.casparHistory ?? []} sarahHistory={data?.sarahHistory ?? []} macroHistory={data?.macroHistory ?? []} />;
      case 6: return <ArchivePage archive={data?.archive ?? []} dailyHistory={data?.dailyHistory ?? []} />;
      case 7: return <SettingsPage settings={settings} onUpdate={updateSettings} onLogout={handleLogout} />;
      default: return null;
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
            <p className="text-[10px] text-slate-500 mt-0.5">Casaa Finance</p>
          </div>
          {tab !== SETTINGS_TAB && (
            <button
              onClick={load}
              disabled={loading}
              className="p-2.5 rounded-xl glass text-slate-400 hover:text-white active:scale-95 transition-all disabled:opacity-40"
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
            </button>
          )}
        </div>
      </header>

      {/* Scrollable content — only this area scrolls */}
      <main className="app-content">
        {data?.error && (
          <div className="mx-4 mb-4 rounded-xl glass border-red-500/30 p-3 text-sm text-red-300 fade-up">
            {data.error}
          </div>
        )}
        {renderPage()}
      </main>

      {/* Fixed bottom tab bar */}
      <TabBar active={tab} onChange={setTab} decisionCount={pendingCount} />
    </div>
  );
}

export default function App() {
  const { authed, grant } = usePinAuth();
  if (!authed) return <PinGate onSuccess={grant} />;
  return <Dashboard />;
}
