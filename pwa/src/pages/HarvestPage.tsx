import { useMemo } from "react";
import type { HarvestScanRow, OptionRow, ScanResultRow } from "../data";
import { HarvestPicksCard } from "../cards/HarvestPicksCard";
import { ScanResultsCard } from "../cards/ScanResultsCard";
import { ActiveHarvestCard, matchHarvestPositions } from "../cards/ActiveHarvestCard";
import { Card } from "../cards/Card";
import { SwipeTabs } from "../components/SwipeTabs";
import { BarChart3 } from "lucide-react";

function MacroBanner({ picks }: { picks: HarvestScanRow[] }) {
  // NO FABRICATED ALL-CLEAR: an empty harvest scan used to fall back to
  // "STANDARD" and render a green "Harvest active · STANDARD · VIX 0" —
  // i.e. a halted/suppressed/missing state displayed as GO. No data = say so.
  if (!picks.length || !picks[0]?.macro_regime) {
    return (
      <div className="rounded-xl border p-3 mb-3 bg-slate-500/10 border-slate-500/20">
        <div className="font-bold text-[length:var(--t-sm)] text-slate-400">No harvest scan data</div>
        <div className="text-[length:var(--t-2xs)] text-slate-500 mt-0.5">
          Regime unknown — the last scan wrote nothing here. Check the scan freshness banner above.
        </div>
      </div>
    );
  }
  const regime = picks[0].macro_regime;
  const vix = Number(picks[0]?.vix || 0);

  const config: Record<string, { bg: string; text: string; label: string }> = {
    STANDARD: { bg: "bg-emerald-500/10 border-emerald-500/20", text: "text-emerald-400", label: "Harvest active" },
    CAUTION:  { bg: "bg-amber-500/10 border-amber-500/20",   text: "text-amber-400",   label: "Harvest active — reduced sizing" },
    HALTED:   { bg: "bg-red-500/10 border-red-500/20",       text: "text-red-400",      label: "Harvest paused — elevated risk" },
  };
  // Unknown regime string renders as CAUTION, not green.
  const c = config[regime] || config.CAUTION;

  return (
    <div className={`rounded-xl border p-3 mb-3 ${c.bg}`}>
      <div className={`font-bold text-[length:var(--t-sm)] ${c.text}`}>{c.label}</div>
      <div className="text-[length:var(--t-2xs)] text-slate-500 mt-0.5">
        {regime}{vix > 0 ? ` · VIX ${vix.toFixed(0)}` : ""}
      </div>
    </div>
  );
}

function HarvestStatsCard({ options }: { options: OptionRow[] }) {
  const cspPositions = options.filter(
    (o) => o.right === "P" && Number(o.qty) < 0,
  );
  if (!cspPositions.length) return null;

  // credit is PER CONTRACT — scale by |qty| or a 3-lot reads as a 1-lot.
  const totalCredit = cspPositions.reduce(
    (s, o) => s + Math.abs(Number(o.credit) || 0) * 100 * Math.max(1, Math.abs(Number(o.qty) || 1)), 0);
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

/** Strategy label map for display. */
const STRATEGY_LABELS: Record<string, string> = {
  CSP: "CSP",
  CC: "CC",
  PCS: "PCS",
  CCS: "CCS",
  IC: "Iron Condor",
  PMCC: "PMCC",
  LONG_CALL: "Long Call",
};

/** Ordering for the strategy tabs — most common first. */
const STRATEGY_ORDER = ["CSP", "CC", "PCS", "CCS", "IC", "PMCC", "LONG_CALL"];

/** Inner content without outer wrapper — used as Options subtab. */
export function HarvestContent({
  harvestScan,
  scanResults,
  options,
  loading,
}: {
  harvestScan: HarvestScanRow[];
  scanResults: ScanResultRow[];
  options: OptionRow[];
  loading: boolean;
}) {
  // ⚠️ Rules of Hooks: every hook below MUST run on every render. The loading
  // early-return lives AFTER all hooks — putting it before them (as it was) made
  // React render 0 hooks while loading then 2 hooks once data arrived, throwing
  // "rendered more hooks than during the previous render" and white-screening the
  // entire app (no error boundary). Hooks first, conditional returns last.
  const picks = harvestScan.filter((r) => r.strategy !== "HALTED");
  const activeHarvests = matchHarvestPositions(options, harvestScan);

  // Group scan_results by strategy — only include strategies that have data
  const byStrategy = useMemo(() => {
    const map = new Map<string, ScanResultRow[]>();
    for (const row of scanResults) {
      const strat = (row.strategy || "").toUpperCase();
      if (!strat) continue;
      const arr = map.get(strat) ?? [];
      arr.push(row);
      map.set(strat, arr);
    }
    // Sort each group by composite_score descending
    for (const [, arr] of map) {
      arr.sort((a, b) => Number(b.composite_score || 0) - Number(a.composite_score || 0));
    }
    return map;
  }, [scanResults]);

  // Build ordered tab list — only tabs with data
  const strategyTabs = useMemo(() => {
    return STRATEGY_ORDER.filter((s) => byStrategy.has(s));
  }, [byStrategy]);

  const hasScanData = strategyTabs.length > 0;

  if (loading && !harvestScan.length && !scanResults.length && !options.length) {
    return <div className="py-8 text-center text-slate-500 text-[length:var(--t-sm)]">Loading…</div>;
  }

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

      {/* Swipeable strategy tabs — all scan_results strategies.
          -mx-4 breaks out of parent px-4 so SwipeTabs has edge-to-edge swipe. */}
      {hasScanData ? (
        <div className={`fade-up ${activeHarvests.length > 0 ? "fade-up-4" : "fade-up-2"} mt-1 -mx-4`}>
          <SwipeTabs
            tabs={strategyTabs.map((s) => ({
              label: `${STRATEGY_LABELS[s] || s} (${byStrategy.get(s)?.length ?? 0})`,
            }))}
            panels={strategyTabs.map((strat) => {
              // CSP tab: use the richer HarvestPicksCard if we have harvest picks
              if (strat === "CSP" && picks.length > 0) {
                return (
                  <div className="px-4 pb-4">
                    <HarvestPicksCard picks={picks} />
                  </div>
                );
              }
              const rows = byStrategy.get(strat) ?? [];
              return (
                <div className="px-4 pb-4">
                  <ScanResultsCard strategy={strat} rows={rows} />
                </div>
              );
            })}
            persistKey="casaa_harvest_strategy_tab"
          />
        </div>
      ) : picks.length > 0 ? (
        /* Fallback: no scan_results strategies, but we have harvest CSP picks. */
        <div className={`fade-up ${activeHarvests.length > 0 ? "fade-up-4" : "fade-up-2"} mt-3`}>
          <HarvestPicksCard picks={picks} />
        </div>
      ) : (
        /* Nothing to show — say so explicitly rather than render blank. */
        <div className="fade-up fade-up-2 mt-8 text-center px-6">
          <p className="text-[length:var(--t-sm)] text-slate-400 font-medium">No scan candidates right now</p>
          <p className="text-[length:var(--t-2xs)] text-slate-600 mt-1.5 leading-relaxed">
            The last scan found nothing to recommend, or the data hasn’t synced yet.
            Pull to refresh, or re-run the Options scan from Settings.
          </p>
        </div>
      )}
    </>
  );
}
