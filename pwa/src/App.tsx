import { useEffect, useState } from "react";
import { fetchDashboard, type DashboardData } from "./data";
import { DailyBriefCard } from "./cards/DailyBriefCard";
import { PnlCard } from "./cards/PnlCard";
import { HouseholdCard } from "./cards/HouseholdCard";
import { RefreshCw } from "lucide-react";

export default function App() {
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
    <div className="min-h-screen bg-slate-900 px-4 pt-safe-top pb-8">
      <header className="flex items-center justify-between py-4">
        <h1 className="text-lg font-semibold text-slate-100">Casaa Finance</h1>
        <button
          onClick={load}
          disabled={loading}
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 active:bg-slate-800 disabled:opacity-40"
        >
          <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
        </button>
      </header>

      {data?.error && (
        <div className="mb-4 rounded-lg bg-red-900/40 border border-red-700 p-3 text-sm text-red-300">
          {data.error}
        </div>
      )}

      <div className="flex flex-col gap-4">
        <DailyBriefCard row={data?.daily ?? null} />
        <PnlCard label="Caspar" currency="USD" snapshot={data?.caspar ?? null} />
        <PnlCard label="Sarah" currency="SGD" snapshot={data?.sarah ?? null} />
        <HouseholdCard caspar={data?.caspar ?? null} sarah={data?.sarah ?? null} macro={data?.macro ?? null} />
      </div>
    </div>
  );
}
