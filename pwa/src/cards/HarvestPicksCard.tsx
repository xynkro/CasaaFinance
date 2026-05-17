import { useState } from "react";
import type { HarvestScanRow } from "../data";
import { Card } from "./Card";
import { Wheat, ChevronDown, ChevronUp } from "lucide-react";

function convColor(c: number) {
  if (c >= 75) return "text-emerald-400 bg-emerald-500/15 border-emerald-500/30";
  if (c >= 50) return "text-amber-400 bg-amber-500/15 border-amber-500/30";
  return "text-slate-400 bg-slate-500/15 border-slate-500/30";
}

function PickRow({ row }: { row: HarvestScanRow }) {
  const [expanded, setExpanded] = useState(false);
  const conv = Number(row.conviction) || 0;
  const credit = Number(row.credit) || 0;
  const yld = Number(row.annual_yield_pct) || 0;
  const dte = Number(row.dte) || 0;
  const strike = Number(row.strike) || 0;
  const isStrangle = row.strategy === "HARVEST_STRANGLE";

  let maint: Record<string, unknown> = {};
  let exitS: Record<string, unknown> = {};
  try { maint = JSON.parse(row.maintenance_signals || "{}"); } catch { /* */ }
  try { exitS = JSON.parse(row.exit_signals || "{}"); } catch { /* */ }

  return (
    <div
      className="border-b border-white/3 last:border-0 py-2.5 cursor-pointer"
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-center gap-2">
        <span className="font-bold text-[length:var(--t-sm)]">{row.ticker}</span>
        <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${convColor(conv)}`}>
          {conv}
        </span>
        <span className="text-[length:var(--t-xs)] text-slate-400 ml-auto">
          {isStrangle ? `$${strike.toFixed(0)}P/${row.notes?.replace("call_strike=", "$")}C` : `$${strike.toFixed(0)}P`}
        </span>
        <span className="text-[length:var(--t-xs)] text-emerald-400 font-mono">${credit.toFixed(2)}</span>
        {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </div>
      <div className="flex gap-3 mt-0.5 text-[length:var(--t-2xs)] text-slate-500">
        <span>{dte}d</span>
        <span>{yld.toFixed(0)}% ann</span>
        <span>IVR {Number(row.iv_rank || 0).toFixed(0)}</span>
        {row.sr_context && <span>{row.sr_context}</span>}
      </div>

      {expanded && (
        <div className="mt-2 space-y-1 text-[length:var(--t-2xs)]">
          <div className="text-slate-400">
            <span className="font-semibold">Maint:</span> {Number(maint.profit_target_pct) || 50}% profit target (optional) · {Number(maint.time_stop_dte) || 21} DTE roll · strike tested at {Number(maint.strike_tested_pct) || 3}%
          </div>
          <div className="text-slate-400">
            <span className="font-semibold">Exit:</span> stop 2x (${Number(exitS.max_loss_value || 0).toFixed(2)}) · {Number(exitS.mechanical_close_dte) || 14} DTE mech close
          </div>
          {isStrangle && (
            <div className="text-amber-400/80">Strangle: close untested side if one tested</div>
          )}
        </div>
      )}
    </div>
  );
}

export function HarvestPicksCard({ picks }: { picks: HarvestScanRow[] }) {
  if (!picks.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Wheat size={14} className="text-amber-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Harvest Picks</h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          Scanner found no candidates passing all filters.
        </p>
      </Card>
    );
  }

  const sorted = [...picks].sort((a, b) => Number(b.conviction) - Number(a.conviction));
  const csps = sorted.filter((p) => p.strategy === "HARVEST_CSP");
  const strangles = sorted.filter((p) => p.strategy === "HARVEST_STRANGLE");

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Wheat size={14} className="text-amber-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Harvest Picks</h2>
        </div>
        <div className="flex items-center gap-2 text-[length:var(--t-2xs)]">
          {csps.length > 0 && <span className="text-emerald-400 tabular-nums">{csps.length} CSP</span>}
          {strangles.length > 0 && (
            <>
              <span className="text-slate-600">·</span>
              <span className="text-amber-400 tabular-nums">{strangles.length} strangle</span>
            </>
          )}
        </div>
      </div>
      <div>
        {sorted.map((p, i) => <PickRow key={`${p.ticker}-${i}`} row={p} />)}
      </div>
    </Card>
  );
}
