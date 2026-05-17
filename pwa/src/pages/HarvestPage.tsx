import type { HarvestScanRow } from "../data";
import { HarvestPicksCard } from "../cards/HarvestPicksCard";

function MacroBanner({ picks }: { picks: HarvestScanRow[] }) {
  const regime = picks[0]?.macro_regime || "STANDARD";
  const vix = Number(picks[0]?.vix || 0);

  const config: Record<string, { bg: string; text: string; label: string }> = {
    STANDARD: { bg: "bg-emerald-500/10 border-emerald-500/20", text: "text-emerald-400", label: "Harvest active" },
    CAUTION:  { bg: "bg-amber-500/10 border-amber-500/20",   text: "text-amber-400",   label: "Harvest active — reduced sizing" },
    HALTED:   { bg: "bg-red-500/10 border-red-500/20",       text: "text-red-400",      label: "Harvest paused — elevated risk" },
  };
  const c = config[regime] || config.STANDARD;

  return (
    <div className={`rounded-xl border p-3 mb-3 ${c.bg}`}>
      <div className={`font-bold text-[length:var(--t-sm)] ${c.text}`}>{c.label}</div>
      <div className="text-[length:var(--t-2xs)] text-slate-500 mt-0.5">
        {regime} · VIX {vix.toFixed(0)}
      </div>
    </div>
  );
}

export function HarvestPage({
  harvestScan,
  loading,
}: {
  harvestScan: HarvestScanRow[];
  loading: boolean;
}) {
  if (loading && !harvestScan.length) {
    return <div className="px-4 py-8 text-center text-slate-500 text-[length:var(--t-sm)]">Loading…</div>;
  }

  // Filter out HALTED placeholder rows
  const picks = harvestScan.filter((r) => r.strategy !== "HALTED");

  return (
    <div className="flex flex-col px-4 pb-4">
      <div className="fade-up fade-up-1 mt-3">
        <MacroBanner picks={harvestScan} />
      </div>
      <div className="fade-up fade-up-2 mt-1">
        <HarvestPicksCard picks={picks} />
      </div>
    </div>
  );
}
