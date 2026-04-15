import type { MacroRow } from "../data";

export function MacroStrip({ macro }: { macro: MacroRow | null }) {
  if (!macro) return null;

  const items = [
    { label: "VIX", value: Number(macro.vix).toFixed(1) },
    { label: "DXY", value: Number(macro.dxy).toFixed(1) },
    { label: "10Y", value: `${Number(macro.us_10y).toFixed(2)}%` },
    { label: "SPX", value: Number(macro.spx).toFixed(0) },
    { label: "USD/SGD", value: Number(macro.usd_sgd).toFixed(3) },
  ];

  return (
    <div className="flex gap-3 overflow-x-auto no-scrollbar py-1 -mx-1 px-1">
      {items.map((item) => (
        <div
          key={item.label}
          className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/5"
        >
          <span className="text-[10px] text-slate-500 font-medium">{item.label}</span>
          <span className="text-xs text-slate-300 font-semibold tabular-nums">{item.value}</span>
        </div>
      ))}
    </div>
  );
}
