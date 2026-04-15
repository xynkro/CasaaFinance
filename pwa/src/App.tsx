import { useEffect, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
import { PinGate, usePinAuth } from "./PinGate";
import { DailyBriefCard } from "./cards/DailyBriefCard";
import { PnlCard } from "./cards/PnlCard";
import { HouseholdCard } from "./cards/HouseholdCard";
import { RefreshCw } from "lucide-react";

function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetchDashboard().then((d) => {
      setData(d);
      setLoading(false);
    });
  };

  useEffect(load, []);

  return (
    <div className="bg-mesh min-h-screen px-4 pt-safe-top pb-10">
      {/* Header */}
      <header className="flex items-center justify-between py-5">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Casaa Finance</h1>
          <p className="text-xs text-slate-500 mt-0.5">Portfolio Dashboard</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-2.5 rounded-xl glass text-slate-400 hover:text-white active:scale-95 transition-all disabled:opacity-40"
        >
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
        </button>
      </header>

      {data?.error && (
        <div className="mb-4 rounded-xl glass border-red-500/30 p-3 text-sm text-red-300 fade-up">
          {data.error}
        </div>
      )}

      <div className="flex flex-col gap-4">
        <div className="fade-up fade-up-1">
          <DailyBriefCard row={data?.daily ?? null} loading={loading && !data} />
        </div>
        <div className="fade-up fade-up-2">
          <PnlCard label="Caspar" currency="USD" snapshot={data?.caspar ?? null} loading={loading && !data} />
        </div>
        <div className="fade-up fade-up-3">
          <PnlCard label="Sarah" currency="SGD" snapshot={data?.sarah ?? null} loading={loading && !data} />
        </div>
        <div className="fade-up fade-up-4">
          <HouseholdCard caspar={data?.caspar ?? null} sarah={data?.sarah ?? null} macro={data?.macro ?? null} />
        </div>
      </div>

      <p className="text-center text-[10px] text-slate-600 mt-8">
        Last refresh {loading ? "..." : new Date().toLocaleTimeString()}
      </p>
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
