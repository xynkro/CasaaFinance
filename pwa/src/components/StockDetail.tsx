import { useEffect, useRef, useState } from "react";
import type { PositionRow, DecisionRow, TechnicalScoreRow, ExitPlanRow } from "../data";
import { X, TrendingUp, TrendingDown, ChevronLeft, Zap, Activity } from "lucide-react";
import { sectorFor } from "../lib/emojis";
import { ExitPlanPanel } from "./ExitPlanPanel";

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function StockDetail({
  position,
  decision,
  ticker: tickerProp,
  techScore,
  techHistory,
  exitPlan,
  currency,
  onClose,
}: {
  position?: PositionRow;
  decision?: DecisionRow;
  ticker?: string;
  techScore?: TechnicalScoreRow;
  techHistory?: TechnicalScoreRow[];
  exitPlan?: ExitPlanRow;
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

      {/* Scrollable body: tech score + chart + TA analysis */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {/* Exit plan panel (when available) — goes first so it's most visible */}
        {exitPlan && <ExitPlanPanel plan={exitPlan} />}

        {/* Our technical analysis panel (when techScore available) */}
        {techScore && <TechAnalysisPanel techScore={techScore} techHistory={techHistory} ticker={ticker} />}

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

// ---------- Technical Analysis Panel (our backend scoring) ----------

const SIGNAL_COLOR: Record<string, string> = {
  BUY: "text-emerald-400",
  HOLD: "text-slate-400",
  "SELL (SL)": "text-red-400",
};

function scoreColor(v: number): string {
  if (v >= 30) return "text-emerald-400";
  if (v <= -30) return "text-red-400";
  return "text-slate-400";
}

function Sparkline({
  values,
  color,
  width = 80,
  height = 24,
}: {
  values: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  if (!values.length) return <div style={{ width, height }} />;
  const min = Math.min(...values, -50);
  const max = Math.max(...values, 50);
  const range = max - min || 1;
  const step = width / Math.max(values.length - 1, 1);
  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  // Draw a horizontal zero line for reference
  const zeroY = height - ((0 - min) / range) * height;
  return (
    <svg width={width} height={height} className="overflow-visible">
      <line x1="0" y1={zeroY} x2={width} y2={zeroY} stroke="rgba(255,255,255,0.08)" strokeDasharray="2 2" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function TechAnalysisPanel({
  techScore: t,
  techHistory,
  ticker,
}: {
  techScore: TechnicalScoreRow;
  techHistory?: TechnicalScoreRow[];
  ticker: string;
}) {
  const close = Number(t.close);
  const rsi = Number(t.rsi_14);
  const stochK = Number(t.stoch_k);
  const stochD = Number(t.stoch_d);
  const support = Number(t.support);
  const resistance = Number(t.resistance);
  const sma20 = Number(t.sma_20);
  const sma50 = Number(t.sma_50);
  const sma200 = Number(t.sma_200);
  const wvf = Number(t.wvf);
  const bbPctB = Number(t.bb_pct_b);
  const catalyst = t.catalyst_flag === "TRUE";
  const squeeze = t.bb_squeeze === "TRUE";
  const wvfBottom = t.wvf_bottom === "TRUE";
  const vol = Number(t.volatility_annual) * 100;

  const scores = [
    { label: "BUY", val: Number(t.score_buy), color: "#10b981" },
    { label: "CSP", val: Number(t.score_csp), color: "#34d399" },
    { label: "CC", val: Number(t.score_cc), color: "#f59e0b" },
    { label: "LC", val: Number(t.score_long_call), color: "#6366f1" },
    { label: "LP", val: Number(t.score_long_put), color: "#ef4444" },
  ];

  // Build historical series for sparklines (last 20 days if available)
  const history = (techHistory ?? [])
    .filter((r) => r.ticker === ticker)
    .slice(-20);
  const histBuy = history.map((r) => Number(r.score_buy));
  const histCsp = history.map((r) => Number(r.score_csp));
  const histCc = history.map((r) => Number(r.score_cc));
  const hasHistory = history.length >= 3;

  const earningsDate = t.earnings_date;
  const earningsDaysAway = Number(t.earnings_days_away);
  const hasEarnings = earningsDate && earningsDaysAway >= 0;

  return (
    <div className="px-4 py-4 border-b border-white/6 space-y-4">
      {/* Signal + trend */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-200">Casaa Score</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-sm font-bold tabular-nums ${SIGNAL_COLOR[t.entry_exit_signal] || "text-slate-400"}`}>
            {t.entry_exit_signal || "HOLD"}
          </span>
          <span className="text-[10px] text-slate-500">·</span>
          <span className="text-[10px] text-slate-400">{t.trend}</span>
          {catalyst && (
            <span className="flex items-center gap-0.5 text-[10px] text-orange-400 ml-1">
              <Zap size={10} />
              <span className="font-semibold">CATALYST</span>
            </span>
          )}
        </div>
      </div>

      {/* Earnings warning banner */}
      {hasEarnings && (
        <div className={`glass rounded-lg p-2.5 border flex items-center gap-2 ${
          earningsDaysAway <= 7
            ? "border-red-500/30 bg-red-500/10"
            : earningsDaysAway <= 14
              ? "border-amber-500/30 bg-amber-500/10"
              : "border-slate-500/20 bg-slate-500/5"
        }`}>
          <Zap size={14} className={
            earningsDaysAway <= 7 ? "text-red-400" :
            earningsDaysAway <= 14 ? "text-amber-400" : "text-slate-400"
          } />
          <div className="flex-1 text-[11px]">
            <span className="font-semibold text-white">Earnings</span>
            <span className="text-slate-400"> · {earningsDate}</span>
            <span className={`ml-2 tabular-nums font-bold ${
              earningsDaysAway <= 7 ? "text-red-400" :
              earningsDaysAway <= 14 ? "text-amber-400" : "text-slate-300"
            }`}>
              {earningsDaysAway === 0 ? "TODAY" : earningsDaysAway === 1 ? "tomorrow" : `${earningsDaysAway}d away`}
            </span>
          </div>
        </div>
      )}

      {/* Strategy scores with sparklines */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <div className="text-[10px] text-slate-600">Strategy scores</div>
          {hasHistory && (
            <div className="text-[10px] text-slate-600">{history.length}d history</div>
          )}
        </div>
        <div className="grid grid-cols-5 gap-1.5">
          {scores.map((s, idx) => {
            const series = idx === 0 ? histBuy : idx === 1 ? histCsp : idx === 2 ? histCc : [];
            return (
              <div key={s.label} className="glass rounded-lg p-2 text-center">
                <div className="text-[10px] text-slate-500">{s.label}</div>
                <div className={`text-sm font-bold tabular-nums ${scoreColor(s.val)}`}>
                  {s.val > 0 ? "+" : ""}{s.val.toFixed(0)}
                </div>
                {hasHistory && series.length >= 3 && idx <= 2 && (
                  <div className="mt-1 flex justify-center">
                    <Sparkline values={series} color={s.color} width={40} height={14} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {t.top_drivers && (
          <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
            {t.top_drivers}
          </p>
        )}
      </div>

      {/* Core indicators */}
      <div>
        <div className="text-[10px] text-slate-600 mb-1.5">Indicators</div>
        <div className="grid grid-cols-4 gap-1.5 text-[10px]">
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">RSI(14)</div>
            <div className={`tabular-nums font-semibold ${
              rsi > 70 ? "text-red-400" : rsi < 30 ? "text-amber-400" : "text-slate-300"
            }`}>
              {rsi.toFixed(0)}
            </div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Stoch K/D</div>
            <div className="tabular-nums text-slate-300">{stochK.toFixed(0)}/{stochD.toFixed(0)}</div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">MACD</div>
            <div className={`tabular-nums font-semibold text-[11px] ${
              t.macd_cross === "bullish" ? "text-emerald-400" :
              t.macd_cross === "bearish" ? "text-red-400" : "text-slate-400"
            }`}>
              {t.macd_cross === "none" ? "—" : t.macd_cross}
            </div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">BB %B</div>
            <div className={`tabular-nums font-semibold ${
              bbPctB > 0.9 ? "text-red-400" : bbPctB < 0.1 ? "text-amber-400" : "text-slate-300"
            }`}>
              {bbPctB.toFixed(2)}{squeeze ? " ⊗" : ""}
            </div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">σ (1y)</div>
            <div className="tabular-nums text-slate-300">{vol.toFixed(0)}%</div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">WVF</div>
            <div className={`tabular-nums font-semibold ${wvfBottom ? "text-emerald-400" : "text-slate-300"}`}>
              {wvf.toFixed(1)}{wvfBottom ? " ↓" : ""}
            </div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Vol/avg</div>
            <div className={`tabular-nums ${
              t.vol_spike_type === "bullish" ? "text-emerald-400" :
              t.vol_spike_type === "bearish" ? "text-red-400" : "text-slate-300"
            }`}>
              {Number(t.vol_ratio).toFixed(1)}×
            </div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Candle</div>
            <div className="tabular-nums text-slate-300 text-[10px] capitalize">
              {t.candle_pattern?.replace("_", " ") || "—"}
            </div>
          </div>
        </div>
      </div>

      {/* Support/resistance + SMAs */}
      <div>
        <div className="text-[10px] text-slate-600 mb-1.5">Levels</div>
        <div className="grid grid-cols-2 gap-1.5 text-[10px]">
          <div className="glass rounded-lg p-2 flex items-center justify-between">
            <span className="text-slate-600">Resistance</span>
            <span className="tabular-nums text-red-400 font-semibold">${resistance.toFixed(2)}</span>
          </div>
          <div className="glass rounded-lg p-2 flex items-center justify-between">
            <span className="text-slate-600">Support</span>
            <span className="tabular-nums text-emerald-400 font-semibold">${support.toFixed(2)}</span>
          </div>
          <div className="glass rounded-lg p-2 flex items-center justify-between">
            <span className="text-slate-600">SMA20</span>
            <span className={`tabular-nums ${close > sma20 ? "text-emerald-400" : "text-red-400"}`}>
              ${sma20.toFixed(2)}
            </span>
          </div>
          <div className="glass rounded-lg p-2 flex items-center justify-between">
            <span className="text-slate-600">SMA50</span>
            <span className={`tabular-nums ${close > sma50 ? "text-emerald-400" : "text-red-400"}`}>
              ${sma50.toFixed(2)}
            </span>
          </div>
          <div className="glass rounded-lg p-2 flex items-center justify-between">
            <span className="text-slate-600">SMA200</span>
            <span className={`tabular-nums ${close > sma200 ? "text-emerald-400" : "text-red-400"}`}>
              {sma200 > 0 ? `$${sma200.toFixed(2)}` : "—"}
            </span>
          </div>
          <div className="glass rounded-lg p-2 flex items-center justify-between">
            <span className="text-slate-600">Fib 0.618</span>
            <span className="tabular-nums text-slate-300">${Number(t.fib_0618).toFixed(2)}</span>
          </div>
        </div>
      </div>

      {t.divergence && t.divergence !== "none" && (
        <div className={`flex items-center gap-1.5 text-[10px] ${
          t.divergence === "bullish" ? "text-emerald-400" : "text-red-400"
        }`}>
          <span className="font-semibold capitalize">{t.divergence} divergence detected</span>
          <span className="text-slate-500">(price vs RSI over 20d)</span>
        </div>
      )}
    </div>
  );
}
