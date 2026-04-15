import { useEffect, useRef } from "react";
import type { PositionRow } from "../data";
import { X, TrendingUp, TrendingDown } from "lucide-react";

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function StockDetail({
  position,
  currency,
  onClose,
}: {
  position: PositionRow;
  currency: "USD" | "SGD";
  onClose: () => void;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const prefix = currency === "SGD" ? "S$" : "$";
  const upl = Number(position.upl);
  const isUp = upl >= 0;
  const uplPct = Number(position.avg_cost) > 0
    ? ((Number(position.last) - Number(position.avg_cost)) / Number(position.avg_cost) * 100)
    : 0;

  useEffect(() => {
    if (!chartRef.current) return;
    // Clear any previous widget
    chartRef.current.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: position.ticker,
      interval: "D",
      timezone: "Asia/Singapore",
      theme: "dark",
      style: "1",
      locale: "en",
      backgroundColor: "rgba(0, 0, 0, 0)",
      gridColor: "rgba(255, 255, 255, 0.03)",
      hide_top_toolbar: false,
      hide_legend: false,
      allow_symbol_change: false,
      save_image: false,
      calendar: false,
      hide_volume: false,
      support_host: "https://www.tradingview.com",
      studies: [
        "STD;SMA",
        "STD;EMA",
        "STD;RSI",
        "STD;MACD",
      ],
    });
    chartRef.current.appendChild(script);
  }, [position.ticker]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#050a18]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 pt-safe-top border-b border-white/6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-slate-700/50 flex items-center justify-center">
            <span className="text-xs font-bold text-slate-200">{position.ticker.slice(0, 4)}</span>
          </div>
          <div>
            <h2 className="text-base font-bold text-white">{position.ticker}</h2>
            <span className="text-xs text-slate-500">
              {Number(position.qty).toFixed(0)} shares @ {fmt(position.avg_cost, prefix)}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-400 hover:text-white active:bg-slate-800"
        >
          <X size={20} />
        </button>
      </div>

      {/* Price + P&L summary */}
      <div className="px-4 py-3 flex items-baseline gap-3 border-b border-white/6">
        <span className="text-2xl font-bold text-white tabular-nums">{fmt(position.last, prefix)}</span>
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold tabular-nums ${
          isUp ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
        }`}>
          {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {uplPct >= 0 ? "+" : ""}{uplPct.toFixed(2)}%
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-px bg-white/5">
        {[
          { label: "Mkt Val", value: fmt(position.mkt_val, prefix) },
          { label: "UPL", value: fmt(position.upl, prefix) },
          { label: "Avg Cost", value: fmt(position.avg_cost, prefix) },
          { label: "Weight", value: `${(Number(position.weight) * 100).toFixed(1)}%` },
        ].map((s) => (
          <div key={s.label} className="bg-[#050a18] px-3 py-2.5 text-center">
            <div className="text-[10px] text-slate-500">{s.label}</div>
            <div className="text-xs font-semibold text-slate-200 tabular-nums mt-0.5">{s.value}</div>
          </div>
        ))}
      </div>

      {/* TradingView chart */}
      <div className="flex-1 min-h-0">
        <div ref={chartRef} className="tradingview-widget-container h-full w-full" />
      </div>
    </div>
  );
}
