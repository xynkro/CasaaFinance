import { useEffect, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
import { PinGate, usePinAuth } from "./PinGate";
import { useSettings } from "./settings";
import { TabBar } from "./components/TabBar";
import { SwipeContainer } from "./components/SwipeContainer";
import { HomePage } from "./pages/HomePage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RefreshCw } from "lucide-react";

const TAB_TITLES = ["Home", "Caspar", "Sarah", "Settings"];

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

  return (
    <div className="bg-mesh min-h-screen pb-20">
      {/* Header */}
      <header className="sticky top-0 z-40 px-4">
        <div className="flex items-center justify-between py-4">
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight">{TAB_TITLES[tab]}</h1>
            <p className="text-[10px] text-slate-500 mt-0.5">Casaa Finance</p>
          </div>
          {tab !== 3 && (
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

      {data?.error && (
        <div className="mx-4 mb-4 rounded-xl glass border-red-500/30 p-3 text-sm text-red-300 fade-up">
          {data.error}
        </div>
      )}

      {/* Swipeable pages */}
      <SwipeContainer activeIndex={tab} onChangeIndex={setTab}>
        <HomePage data={data} loading={loading} />
        <PortfolioPage
          label="Caspar"
          currency="USD"
          snapshot={data?.caspar ?? null}
          positions={data?.casparPositions ?? []}
          loading={loading && !data}
        />
        <PortfolioPage
          label="Sarah"
          currency="SGD"
          snapshot={data?.sarah ?? null}
          positions={data?.sarahPositions ?? []}
          loading={loading && !data}
        />
        <SettingsPage
          settings={settings}
          onUpdate={updateSettings}
          onLogout={handleLogout}
        />
      </SwipeContainer>

      <TabBar active={tab} onChange={setTab} />
    </div>
  );
}

export default function App() {
  const { authed, grant } = usePinAuth();

  if (!authed) {
    return <PinGate onSuccess={grant} />;
  }

  return <Dashboard />;
}
