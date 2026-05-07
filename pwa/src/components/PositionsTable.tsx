import { useState } from "react";
import type { PositionRow, TechnicalScoreRow, ExitPlanRow, LivePriceRow } from "../data";
import { StockDetail } from "./StockDetail";
import { ExitStatusBadge } from "./ExitPlanPanel";
import { ChevronRight } from "lucide-react";

function fmt(v: string, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pctFmt(v: string): { text: string; positive: boolean } {
  const n = Number(v);
  if (isNaN(n)) return { text: "—", positive: true };
  return {
    text: `${(n * 100).toFixed(1)}%`,
    positive: n >= 0,
  };
}

export function PositionsTable({
  positions,
  currency,
  technicalScores,
  technicalScoresHistory,
  exitPlans,
  account,
  livePrices,
}: {
  positions: PositionRow[];
  currency: "USD" | "SGD";
  technicalScores?: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
  exitPlans?: ExitPlanRow[];
  account?: "caspar" | "sarah";
  livePrices?: Map<string, LivePriceRow>;
}) {
  // Helper: live mkt_val for a position. Falls back to grab-time mkt_val
  // when there's no live price (e.g. SGX symbol TV doesn't quote).
  const liveMktVal = (pos: PositionRow): number => {
    const lp = livePrices?.get((pos.ticker || "").toUpperCase());
    if (lp && Number(lp.last) > 0) {
      return Number(pos.qty || 0) * Number(lp.last);
    }
    return Number(pos.mkt_val || 0);
  };
  // Helper: live UPL.
  const liveUpl = (pos: PositionRow): number => {
    const lp = livePrices?.get((pos.ticker || "").toUpperCase());
    if (lp && Number(lp.last) > 0) {
      return Number(pos.qty || 0) * (Number(lp.last) - Number(pos.avg_cost || 0));
    }
    return Number(pos.upl || 0);
  };
  const [selected, setSelected] = useState<PositionRow | null>(null);
  const prefix = currency === "SGD" ? "S$" : "$";
  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) techByTicker.set(t.ticker, t);
  const exitByTicker = new Map<string, ExitPlanRow>();
  for (const e of exitPlans ?? []) {
    if (e.position_type === "STOCK" && (!account || e.account === account)) {
      exitByTicker.set(e.ticker, e);
    }
  }

  if (!positions.length) {
    return (
      <div className="glass rounded-2xl p-5">
        <p className="text-[length:var(--t-sm)] text-slate-500">No positions data yet</p>
      </div>
    );
  }

  // Sort by LIVE mkt_val so today's biggest mover floats up. Falls back to
  // grab-time when no live price (preserves existing UX for SGX positions).
  const sorted = [...positions].sort((a, b) => liveMktVal(b) - liveMktVal(a));
  // Total live mkt_val — used to recompute weight % so the % column reflects
  // current allocation rather than stale grab-time weight.
  const totalLiveMktVal = sorted.reduce((s, p) => s + liveMktVal(p), 0);

  return (
    <>
      <div className="glass rounded-2xl overflow-hidden">
        <div className="px-5 pt-4 pb-2 flex items-center justify-between">
          <h3 className="text-[length:var(--t-xs)] font-medium text-slate-500 uppercase tracking-wider">Positions</h3>
          <span className="text-[length:var(--t-2xs)] text-slate-600">{positions.length} holdings</span>
        </div>

        <div className="divide-y divide-white/5">
          {sorted.map((pos) => {
            const upl = liveUpl(pos);
            const mv = liveMktVal(pos);
            const weightPct = totalLiveMktVal > 0 ? mv / totalLiveMktVal : Number(pos.weight);
            const weight = pctFmt(String(weightPct));
            const isUp = upl >= 0;
            const exitPlan = exitByTicker.get(pos.ticker);

            return (
              <button
                key={pos.ticker}
                onClick={() => setSelected(pos)}
                className="w-full px-5 py-3 flex items-center justify-between active:bg-white/3 transition-colors text-left"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                    isUp ? "bg-emerald-500/8" : "bg-red-500/8"
                  }`}>
                    <span className="text-[length:var(--t-xs)] font-bold text-slate-200">
                      {pos.ticker.slice(0, 4)}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[length:var(--t-sm)] font-semibold text-slate-100">{pos.ticker}</span>
                      <ExitStatusBadge plan={exitPlan} />
                    </div>
                    <div className="text-[length:var(--t-xs)] text-slate-500 font-tabular">
                      {Number(pos.qty).toFixed(0)} @ {fmt(pos.avg_cost, prefix)}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0 ml-3">
                  <div className="text-right">
                    <div className="text-[length:var(--t-sm)] font-semibold text-slate-100 font-tabular">
                      {fmt(String(mv), prefix)}
                    </div>
                    <div className="flex items-center justify-end gap-2">
                      <span className={`text-[length:var(--t-xs)] font-medium font-tabular ${isUp ? "text-emerald-400" : "text-red-400"}`}>
                        {isUp ? "+" : ""}{fmt(String(upl), "")}
                      </span>
                      <span className="text-[length:var(--t-2xs)] text-slate-500 font-tabular">
                        {weight.text}
                      </span>
                    </div>
                  </div>
                  <ChevronRight size={14} className="text-slate-600" />
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {selected && (
        <StockDetail
          position={selected}
          techScore={techByTicker.get(selected.ticker)}
          techHistory={technicalScoresHistory}
          exitPlan={exitByTicker.get(selected.ticker)}
          currency={currency}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
