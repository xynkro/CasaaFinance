import type { MacroRow } from "../data";

export function MacroStrip({ macro }: { macro: MacroRow | null }) {
  if (!macro) return null;

  const vix    = Number(macro.vix);
  const dxy    = Number(macro.dxy);
  const us10y  = Number(macro.us_10y);
  const spx    = Number(macro.spx);
  const usdsgd = Number(macro.usd_sgd);

  // VIX colour coding
  const vixColor = vix > 25 ? "#f87171" : vix > 18 ? "#fbbf24" : "#34d399";

  const items = [
    { label: "VIX",      value: vix.toFixed(1),             color: vixColor,             emoji: "🌡️" },
    { label: "DXY",      value: dxy.toFixed(1),             color: "rgb(148 163 184)",   emoji: "💵" },
    { label: "10Y",      value: `${us10y.toFixed(2)}%`,     color: "rgb(148 163 184)",   emoji: "📊" },
    { label: "SPX",      value: spx >= 1000 ? `${(spx/1000).toFixed(2)}k` : spx.toFixed(0), color: "rgb(148 163 184)", emoji: "📈" },
    { label: "USD/SGD",  value: usdsgd.toFixed(3),          color: "rgb(148 163 184)",   emoji: "🇸🇬" },
  ];

  return (
    <div className="flex gap-2 overflow-x-auto no-scrollbar py-0.5 -mx-1 px-1">
      {items.map((item) => (
        <div
          key={item.label}
          className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-full"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.06)",
          }}
        >
          <span className="text-[11px] leading-none">{item.emoji}</span>
          <span className="text-[10px] font-medium" style={{ color: "rgb(100 116 139)" }}>
            {item.label}
          </span>
          <span
            className="text-[11px] font-semibold tabular-nums"
            style={{ color: item.color }}
          >
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}
