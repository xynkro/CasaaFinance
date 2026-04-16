import { useEffect, useRef, useState } from "react";
import type { PositionRow, DecisionRow } from "../data";
import { X, TrendingUp, TrendingDown, ChevronLeft } from "lucide-react";
import { sectorFor } from "../lib/emojis";

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function StockDetail({
  position,
  decision,
  ticker: tickerProp,
  currency,
  onClose,
}: {
  position?: PositionRow;
  decision?: DecisionRow;
  ticker?: string;
  currency: "USD" | "SGD";
  onClose: () => void;
}) {
  const ticker = tickerProp ?? position?.ticker ?? decision?.ticker ?? "";
  const chartRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const touchRef = useRef<{ startX: number; startY: number; moving: boolean }>({
    startX: 0, startY: 0, moving: false,
  });
  const [dragX, setDragX] = useState(0);

  const prefix = currency === "SGD" ? "S$" : "$";
  const upl = position ? Number(position.upl) : 0;
  const isUp = upl >= 0;
  const avgCost = position ? Number(position.avg_cost) : 0;
  const uplPct = avgCost > 0 ? ((Number(position?.last) - avgCost) / avgCost) * 100 : 0;
  const { sector, emoji } = sectorFor(ticker);

  // ---- Swipe-right-to-close ----
  const SWIPE_THRESHOLD = 80;

  const onTouchStart = (e: React.TouchEvent) => {
    touchRef.current = {
      startX: e.touches[0].clientX,
      startY: e.touches[0].clientY,
      moving: false,
    };
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchRef.current.startX;
    const dy = e.touches[0].clientY - touchRef.current.startY;
    // Ignore vertical-dominant motion (TradingView chart needs pinch/scroll)
    if (!touchRef.current.moving) {
      if (Math.abs(dy) > Math.abs(dx)) return;
      if (Math.abs(dx) < 10) return;
      // Only activate swipe-close on rightward gesture
      if (dx <= 0) return;
      touchRef.current.moving = true;
    }
    if (touchRef.current.moving && dx > 0) {
      setDragX(dx);
    }
  };

  const onTouchEnd = () => {
    if (touchRef.current.moving && dragX > SWIPE_THRESHOLD) {
      onClose();
    } else {
      setDragX(0);
    }
    touchRef.current.moving = false;
  };

  // ---- TradingView widgets ----
  useEffect(() => {
    // Advanced chart
    if (chartRef.current) {
      chartRef.current.innerHTML = "";
      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
      script.async = true;
      script.innerHTML = JSON.stringify({
        autosize: true,
        symbol: ticker,
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
        studies: ["STD;SMA", "STD;EMA", "STD;RSI", "STD;MACD"],
      });
      chartRef.current.appendChild(script);
    }

    // Technical Analysis summary (buy/sell/neutral + oscillator + MA breakdown)
    if (taRef.current) {
      taRef.current.innerHTML = "";
      const ta = document.createElement("script");
      ta.src = "https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js";
      ta.async = true;
      ta.innerHTML = JSON.stringify({
        colorTheme: "dark",
        displayMode: "multiple",
        isTransparent: true,
        locale: "en",
        interval: "1D",
        disableInterval: false,
        width: "100%",
        height: 450,
        symbol: ticker,
        showIntervalTabs: true,
      });
      taRef.current.appendChild(ta);
    }
  }, [ticker]);

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex flex-col bg-[#050a18] transition-transform"
      style={{
        transform: `translateX(${dragX}px)`,
        transitionDuration: touchRef.current.moving ? "0ms" : "250ms",
        opacity: 1 - Math.min(dragX / 400, 0.3),
      }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {/* Header — with back arrow hint */}
      <div className="flex items-center justify-between px-3 py-3 pt-safe-top border-b border-white/6">
        <button
          onClick={onClose}
          className="flex items-center gap-1 pr-2 py-2 text-indigo-400 active:text-indigo-300"
          aria-label="Back"
        >
          <ChevronLeft size={20} />
          <span className="text-sm">Back</span>
        </button>
        <div className="flex items-center gap-2.5">
          <span className="text-lg">{emoji}</span>
          <div className="text-right">
            <h2 className="text-base font-bold text-white leading-tight">{ticker}</h2>
            <span className="text-[10px] text-slate-500">{sector}</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-500 active:text-white"
          aria-label="Close"
        >
          <X size={18} />
        </button>
      </div>

      {/* Price + P&L (position mode) */}
      {position && (
        <div className="px-4 py-3 flex items-baseline gap-3 border-b border-white/6">
          <span className="text-2xl font-bold text-white tabular-nums">{fmt(position.last, prefix)}</span>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold tabular-nums ${
            isUp ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
          }`}>
            {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {uplPct >= 0 ? "+" : ""}{uplPct.toFixed(2)}%
          </span>
          <span className="text-xs text-slate-500 ml-auto">
            {Number(position.qty).toFixed(0)} @ {fmt(position.avg_cost, prefix)}
          </span>
        </div>
      )}

      {/* Decision info (decision mode) */}
      {decision && (
        <div className="px-4 py-3 border-b border-white/6 space-y-2">
          <p className="text-sm text-slate-300 leading-relaxed">{decision.thesis_1liner}</p>
          <div className="flex items-center gap-4 text-xs">
            {decision.bucket && (
              <span className="text-[10px] font-medium text-indigo-400 uppercase bg-indigo-500/10 px-2 py-0.5 rounded">
                {decision.bucket}
              </span>
            )}
            {decision.entry && (
              <span className="text-slate-500">
                Entry <span className="text-white font-semibold tabular-nums">{fmt(decision.entry, prefix)}</span>
              </span>
            )}
            {decision.target && (
              <span className="text-slate-500">
                Target <span className="text-emerald-400 font-semibold tabular-nums">{fmt(decision.target, prefix)}</span>
              </span>
            )}
            {decision.conv && Number(decision.conv) > 0 && (
              <span className="text-slate-500">
                Conv <span className="text-amber-400 font-semibold">{Math.round(Number(decision.conv))}/5</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Stats grid (position mode) */}
      {position && (
        <div className="grid grid-cols-4 gap-px bg-white/5 shrink-0">
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
      )}

      {/* Scrollable body: chart + technical analysis */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {/* TradingView advanced chart */}
        <div className="h-[55vh] min-h-[320px] border-b border-white/6">
          <div ref={chartRef} className="tradingview-widget-container h-full w-full" />
        </div>

        {/* Technical Analysis summary — auto-interprets SMA/EMA/RSI/MACD */}
        <div className="px-4 pt-4 pb-2">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-base">🧭</span>
            <h3 className="text-sm font-semibold text-slate-200">Technical Analysis</h3>
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed mb-2">
            Real-time rating from moving averages + oscillators. Switch intervals (1h / 1D / 1W / 1M) to see
            short-term vs long-term bias. <span className="text-emerald-400">Buy</span> = majority of
            indicators bullish; <span className="text-red-400">Sell</span> = majority bearish.
          </p>
        </div>
        <div className="px-2 pb-4">
          <div ref={taRef} className="tradingview-widget-container w-full" />
        </div>
      </div>
    </div>
  );
}
