import type { SnapshotRow, MacroRow } from "../data";
import { Card } from "./Card";
import { Users } from "lucide-react";

export function HouseholdCard({
  caspar,
  sarah,
  macro,
}: {
  caspar: SnapshotRow | null;
  sarah: SnapshotRow | null;
  macro: MacroRow | null;
}) {
  const usdSgd = Number(macro?.usd_sgd) || 0;
  const casparUsd = Number(caspar?.net_liq) || 0;
  const sarahSgd = Number(sarah?.net_liq) || 0;

  const hasBoth = casparUsd > 0 && sarahSgd > 0 && usdSgd > 0;
  const sarahUsd = usdSgd > 0 ? sarahSgd / usdSgd : 0;
  const totalUsd = casparUsd + sarahUsd;

  if (!hasBoth) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Users size={16} />
          <span className="text-[length:var(--t-sm)]">Household — waiting for both portfolios + FX rate</span>
        </div>
      </Card>
    );
  }

  const fmtUsd = (n: number) =>
    `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const fmtSgd = (n: number) =>
    `S$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const casparPct = (casparUsd / totalUsd) * 100;
  const sarahPct = (sarahUsd / totalUsd) * 100;

  return (
    <Card variant="bright">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Users size={14} className="text-indigo-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Household</h2>
        </div>
        <span className="text-[length:var(--t-xs)] text-slate-500 font-tabular">
          USD/SGD {usdSgd.toFixed(4)}
        </span>
      </div>

      <div className="text-3xl font-bold text-white tracking-tight font-tabular mb-4">
        {fmtUsd(totalUsd)}
      </div>

      {/* Proportion bar */}
      <div className="flex h-2 rounded-full overflow-hidden mb-4">
        <div className="bg-blue-500/70 transition-all" style={{ width: `${casparPct}%` }} />
        <div className="bg-violet-500/70 transition-all" style={{ width: `${sarahPct}%` }} />
      </div>

      <div className="space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-blue-500/70" />
            <span className="text-[length:var(--t-sm)] text-slate-300">Caspar</span>
          </div>
          <span className="text-[length:var(--t-sm)] text-white font-medium font-tabular">{fmtUsd(casparUsd)}</span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-violet-500/70" />
            <span className="text-[length:var(--t-sm)] text-slate-300">Sarah</span>
          </div>
          <div className="text-right">
            <span className="text-[length:var(--t-sm)] text-white font-medium font-tabular">{fmtUsd(sarahUsd)}</span>
            <span className="text-[length:var(--t-xs)] text-slate-500 ml-1.5 font-tabular">({fmtSgd(sarahSgd)})</span>
          </div>
        </div>
      </div>
    </Card>
  );
}
