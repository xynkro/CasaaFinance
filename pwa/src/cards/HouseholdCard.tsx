import type { SnapshotRow, MacroRow } from "../data";
import { Card } from "./Card";

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
        <h2 className="text-sm font-medium text-slate-400 mb-1">Household</h2>
        <p className="text-sm text-slate-500">
          Waiting for both portfolios + FX rate
        </p>
      </Card>
    );
  }

  const fmtUsd = (n: number) =>
    `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const fmtSgd = (n: number) =>
    `S$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <Card>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-medium text-slate-400">Household</h2>
        <span className="text-xs text-slate-500">
          USD/SGD {usdSgd.toFixed(4)}
        </span>
      </div>

      <div className="text-2xl font-bold text-slate-100 mb-2">
        {fmtUsd(totalUsd)}
      </div>

      <div className="space-y-1 text-sm text-slate-300">
        <div className="flex justify-between">
          <span>Caspar</span>
          <span>{fmtUsd(casparUsd)}</span>
        </div>
        <div className="flex justify-between">
          <span>Sarah</span>
          <span>
            {fmtUsd(sarahUsd)}{" "}
            <span className="text-xs text-slate-500">({fmtSgd(sarahSgd)})</span>
          </span>
        </div>
      </div>
    </Card>
  );
}
