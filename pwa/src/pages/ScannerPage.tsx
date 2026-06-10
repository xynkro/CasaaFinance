import { useState, useMemo } from "react";
import type { IvSurfaceScanRow } from "../data";
import { numeric } from "../data";
import { IvSmileChart } from "../cards/IvSmileChart";
import { TopCandidatesCard } from "../cards/TopCandidatesCard";
import { ChainViewCard } from "../cards/ChainViewCard";

/* ---------- types ---------- */

interface ScannerPageProps {
  ivSurfaceScan: IvSurfaceScanRow[];
  loading: boolean;
}

/* ---------- component ---------- */

export function ScannerPage({ ivSurfaceScan, loading }: ScannerPageProps) {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<"P" | "C" | "both">("P");

  /* ---- derived lists ---- */

  const allTickers = useMemo(() => {
    const s = new Set(ivSurfaceScan.map((r) => r.ticker).filter((v): v is string => !!v));
    return [...s].sort();
  }, [ivSurfaceScan]);

  const ticker = selectedTicker ?? allTickers[0] ?? null;

  const tickerContracts = useMemo(
    () => ivSurfaceScan.filter((r) => r.ticker === ticker),
    [ivSurfaceScan, ticker],
  );

  const expiries = useMemo(() => {
    const s = new Set(tickerContracts.map((r) => r.expiry).filter((v): v is string => !!v));
    return [...s].sort();
  }, [tickerContracts]);

  const expiry =
    selectedExpiry && expiries.includes(selectedExpiry)
      ? selectedExpiry
      : expiries[0] ?? null;

  const chartContracts = useMemo(() => {
    let filtered = tickerContracts.filter((r) => r.expiry === expiry);
    if (filterType !== "both") filtered = filtered.filter((r) => r.type === filterType);
    return filtered;
  }, [tickerContracts, expiry, filterType]);

  const chainContracts = useMemo(
    () => tickerContracts.filter((r) => r.expiry === expiry),
    [tickerContracts, expiry],
  );

  // First contract WITH a real spot — not blindly [0]. A leading row with a
  // blank/zero spot (truncated or partial data) was rendering "Spot 0.00" and
  // breaking the chart scale even when other rows carried the price.
  const spot = useMemo(() => {
    for (const r of chartContracts) {
      const s = numeric(r.spot);
      if (s > 0) return s;
    }
    for (const r of tickerContracts) {
      const s = numeric(r.spot);
      if (s > 0) return s;
    }
    return 0;
  }, [chartContracts, tickerContracts]);

  /* ---- empty state ---- */

  if (ivSurfaceScan.length === 0 && !loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh] px-6">
        <p className="text-slate-500 text-[length:var(--t-sm)] text-center">
          No scan data yet. Scanner runs daily at 8 am ET pre-market.
        </p>
      </div>
    );
  }

  /* ---- callbacks ---- */

  const handleSelectContract = (row: IvSurfaceScanRow) => {
    if (row.ticker) setSelectedTicker(row.ticker);
    if (row.expiry) setSelectedExpiry(row.expiry);
  };

  const handleTickerChange = (t: string) => {
    setSelectedTicker(t);
    setSelectedExpiry(null); // reset expiry so it auto-selects first for new ticker
  };

  /* ---- type filter buttons ---- */

  const TYPE_OPTIONS: Array<{ value: "P" | "C" | "both"; label: string }> = [
    { value: "P", label: "P" },
    { value: "C", label: "C" },
    { value: "both", label: "Both" },
  ];

  /* ---- render ---- */

  return (
    <div className="space-y-4 px-4 pb-24">
      {/* Ticker chips */}
      <div className="overflow-x-auto flex gap-1.5 no-scrollbar -mx-4 px-4">
        {allTickers.map((t) => (
          <button
            key={t}
            onClick={() => handleTickerChange(t)}
            className={`shrink-0 px-3 py-1.5 rounded-full text-[length:var(--t-xs)] font-medium transition-colors ${
              t === ticker
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                : "bg-white/5 text-slate-500 border border-white/5"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Controls row: expiry dropdown + type toggle */}
      <div className="flex items-center gap-3">
        {/* Expiry select */}
        <select
          value={expiry ?? ""}
          onChange={(e) => setSelectedExpiry(e.target.value)}
          className="rounded-lg px-3 py-1.5 text-[length:var(--t-xs)] text-slate-300 font-medium appearance-none"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
          }}
        >
          {expiries.map((exp) => (
            <option key={exp} value={exp}>
              {exp}
            </option>
          ))}
        </select>

        {/* Type filter toggle */}
        <div className="flex gap-1">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilterType(opt.value)}
              className={`px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors ${
                filterType === opt.value
                  ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                  : "bg-white/5 text-slate-500 border border-white/5"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* IV Smile Chart */}
      {chartContracts.length > 0 && (
        <IvSmileChart contracts={chartContracts} spot={spot} />
      )}

      {/* Top Candidates */}
      <TopCandidatesCard
        contracts={ivSurfaceScan}
        onSelectContract={handleSelectContract}
      />

      {/* Chain View */}
      {chainContracts.length > 0 && (
        <ChainViewCard contracts={chainContracts} spot={spot} />
      )}
    </div>
  );
}
