import type { HarvestScanRow, OptionRow } from "../data";
import { HarvestPicksCard } from "../cards/HarvestPicksCard";
import { ActiveHarvestCard, matchHarvestPositions } from "../cards/ActiveHarvestCard";
import { Card } from "../cards/Card";
import { BarChart3 } from "lucide-react";

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

function HarvestStatsCard({ options }: { options: OptionRow[] }) {
  const cspPositions = options.filter(
    (o) => o.right === "P" && Number(o.qty) < 0,
  );
  if (!cspPositions.length) return null;

  const totalCredit = cspPositions.reduce((s, o) => s + Math.abs(Number(o.credit) || 0) * 100, 0);
  const totalUpl = cspPositions.reduce((s, o) => s + (Number(o.upl) || 0), 0);
  const winning = cspPositions.filter((o) => (Number(o.upl) || 0) > 0).length;
  const winRate = cspPositions.length > 0 ? (winning / cspPositions.length) * 100 : 0;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <BarChart3 size={14} className="text-indigo-400" />
        <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Harvest Stats</h2>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">Open CSPs</div>
          <div className="text-[length:var(--t-sm)] font-bold text-white tabular-nums">{cspPositions.length}</div>
        </div>
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">Credit</div>
          <div className="text-[length:var(--t-sm)] font-bold text-emerald-400 tabular-nums">${totalCredit.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">P&L</div>
          <div className={`text-[length:var(--t-sm)] font-bold tabular-nums ${totalUpl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {totalUpl >= 0 ? "+" : ""}${totalUpl.toFixed(0)}
          </div>
        </div>
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">Win Rate</div>
          <div className="text-[length:var(--t-sm)] font-bold text-white tabular-nums">{winRate.toFixed(0)}%</div>
        </div>
      </div>
    </Card>
  );
}

/** Inner content without outer wrapper — used as Options subtab. */
export function HarvestContent({
  harvestScan,
  options,
  loading,
}: {
  harvestScan: HarvestScanRow[];
  options: OptionRow[];
  loading: boolean;
}) {
  if (loading && !harvestScan.length && !options.length) {
    return <div className="py-8 text-center text-slate-500 text-[length:var(--t-sm)]">Loading…</div>;
  }

  const picks = harvestScan.filter((r) => r.strategy !== "HALTED");
  const activeHarvests = matchHarvestPositions(options, harvestScan);

  return (
    <>
      <div className="fade-up fade-up-1 mt-3">
        <MacroBanner picks={harvestScan} />
      </div>
      {activeHarvests.length > 0 && (
        <div className="fade-up fade-up-2 mt-1">
          <ActiveHarvestCard harvests={activeHarvests} />
        </div>
      )}
      {activeHarvests.length > 0 && (
        <div className="fade-up fade-up-3 mt-3">
          <HarvestStatsCard options={options} />
        </div>
      )}
      <div className={`fade-up ${activeHarvests.length > 0 ? "fade-up-4" : "fade-up-2"} mt-3`}>
        <HarvestPicksCard picks={picks} />
      </div>
    </>
  );
}
