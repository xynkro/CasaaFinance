import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { PositionRow, DecisionRow, TechnicalScoreRow, ExitPlanRow } from "../data";
import { X, TrendingUp, TrendingDown, ChevronLeft, Zap, Activity, BarChart2 } from "lucide-react";
import { sectorFor } from "../lib/emojis";
import { ExitPlanPanel } from "./ExitPlanPanel";

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ─── Sparkline ───────────────────────────────────────────────────────────────
function Sparkline({ values, color, width = 80, height = 28 }: {
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
  const points = values.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const zeroY = height - ((0 - min) / range) * height;
  return (
    <svg width={width} height={height} className="overflow-visible">
      <line x1="0" y1={zeroY} x2={width} y2={zeroY} stroke="rgba(255,255,255,0.07)" strokeDasharray="2 2" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Score chip ───────────────────────────────────────────────────────────────
function ScoreChip({ label, val, color, histValues }: {
  label: string;
  val: number;
  color: string;
  histValues?: number[];
}) {
  const textColor = val >= 30 ? "#34d399" : val <= -30 ? "#f87171" : "rgb(148 163 184)";
  return (
    <div
      className="flex flex-col gap-1.5 rounded-2xl p-3"
      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-slate-500">{label}</span>
        <span className="text-base font-bold tabular-nums" style={{ color: textColor }}>
          {val > 0 ? "+" : ""}{val.toFixed(0)}
        </span>
      </div>
      {histValues && histValues.length >= 3 && (
        <Sparkline values={histValues} color={color} width={72} height={26} />
      )}
    </div>
  );
}

// ─── Indicator tile ──────────────────────────────────────────────────────────
function IndicatorTile({ label, value, sub, valueColor }: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div
      className="rounded-2xl p-3"
      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      <div className="text-[11px] text-slate-500 mb-1">{label}</div>
      <div className="text-[15px] font-semibold tabular-nums" style={{ color: valueColor ?? "rgb(226 232 240)" }}>
        {value}
      </div>
      {sub && <div className="text-[10px] text-slate-600 mt-0.5">{sub}</div>}
    </div>
  );
}

// ─── Level row ───────────────────────────────────────────────────────────────
function LevelRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/5">
      <span className="text-[13px] text-slate-400">{label}</span>
      <span className="text-[13px] font-semibold tabular-nums" style={{ color }}>{value}</span>
    </div>
  );
}

// ─── Tech Analysis Panel ─────────────────────────────────────────────────────
const SIGNAL_COLOR: Record<string, string> = {
  BUY: "#34d399",
  HOLD: "rgb(148 163 184)",
  "SELL (SL)": "#f87171",
};

function TechAnalysisPanel({
  techScore: t,
  techHistory,
  ticker,
}: {
  techScore: TechnicalScoreRow;
  techHistory?: TechnicalScoreRow[];
  ticker: string;
}) {
  const close     = Number(t.close);
  const rsi       = Number(t.rsi_14);
  const stochK    = Number(t.stoch_k);
  const stochD    = Number(t.stoch_d);
  const support   = Number(t.support);
  const resistance= Number(t.resistance);
  const sma20     = Number(t.sma_20);
  const sma50     = Number(t.sma_50);
  const sma200    = Number(t.sma_200);
  const wvf       = Number(t.wvf);
  const bbPctB    = Number(t.bb_pct_b);
  const catalyst  = t.catalyst_flag === "TRUE";
  const squeeze   = t.bb_squeeze === "TRUE";
  const wvfBottom = t.wvf_bottom === "TRUE";
  const vol       = Number(t.volatility_annual) * 100;
  const volRatio  = Number(t.vol_ratio);
  const earningsDate     = t.earnings_date;
  const earningsDaysAway = Number(t.earnings_days_away);
  const hasEarnings = earningsDate && earningsDaysAway >= 0;
  const signalColor = SIGNAL_COLOR[t.entry_exit_signal] ?? "rgb(148 163 184)";

  const history = (techHistory ?? []).filter((r) => r.ticker === ticker).slice(-20);
  const histBuy = history.map((r) => Number(r.score_buy));
  const histCsp = history.map((r) => Number(r.score_csp));
  const histCc  = history.map((r) => Number(r.score_cc));
  const histLc  = history.map((r) => Number(r.score_long_call));
  const histLp  = history.map((r) => Number(r.score_long_put));
  const hasHist = history.length >= 3;

  const scores = [
    { label: "BUY", val: Number(t.score_buy), color: "#10b981", hist: histBuy },
    { label: "CSP", val: Number(t.score_csp), color: "#34d399", hist: histCsp },
    { label: "CC",  val: Number(t.score_cc),  color: "#f59e0b", hist: histCc  },
    { label: "LC",  val: Number(t.score_long_call), color: "#6366f1", hist: histLc },
    { label: "LP",  val: Number(t.score_long_put),  color: "#ef4444", hist: histLp },
  ];

  return (
    <div className="px-4 py-5 space-y-5 border-b border-white/5">

      {/* Signal row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={15} style={{ color: "rgb(var(--accent-rgb))" }} />
          <span className="text-[15px] font-semibold text-slate-200">Casaa Score</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-bold tabular-nums" style={{ color: signalColor }}>
            {t.entry_exit_signal || "HOLD"}
          </span>
          <span className="text-slate-600">·</span>
          <span className="text-sm text-slate-400">{t.trend}</span>
          {catalyst && (
            <span className="inline-flex items-center gap-0.5 text-xs text-orange-400 font-semibold">
              <Zap size={11} /> CATALYST
            </span>
          )}
        </div>
      </div>

      {/* Earnings warning */}
      {hasEarnings && (
        <div
          className="flex items-center gap-3 rounded-2xl px-4 py-3"
          style={{
            background: earningsDaysAway <= 7 ? "rgba(239,68,68,0.1)" :
                        earningsDaysAway <= 14 ? "rgba(251,191,36,0.1)" : "rgba(255,255,255,0.04)",
            border: `1px solid ${earningsDaysAway <= 7 ? "rgba(239,68,68,0.25)" :
                                  earningsDaysAway <= 14 ? "rgba(251,191,36,0.25)" : "rgba(255,255,255,0.07)"}`,
          }}
        >
          <Zap size={16} style={{
            color: earningsDaysAway <= 7 ? "#f87171" : earningsDaysAway <= 14 ? "#fbbf24" : "rgb(148 163 184)"
          }} />
          <div>
            <span className="text-sm font-semibold text-white">Earnings</span>
            <span className="text-sm text-slate-400"> · {earningsDate}</span>
            <span className="ml-2 text-sm font-bold tabular-nums" style={{
              color: earningsDaysAway <= 7 ? "#f87171" : earningsDaysAway <= 14 ? "#fbbf24" : "rgb(226 232 240)"
            }}>
              {earningsDaysAway === 0 ? "TODAY" : earningsDaysAway === 1 ? "tomorrow" : `${earningsDaysAway}d away`}
            </span>
          </div>
        </div>
      )}

      {/* Strategy scores — 3 + 2 grid */}
      <div>
        <div className="flex items-center justify-between mb-2.5">
          <span className="label-caps">Strategy Scores</span>
          {hasHist && <span className="label-caps">{history.length}d history</span>}
        </div>
        <div className="grid grid-cols-3 gap-2 mb-2">
          {scores.slice(0, 3).map((s) => (
            <ScoreChip key={s.label} label={s.label} val={s.val} color={s.color}
              histValues={hasHist ? s.hist : undefined} />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          {scores.slice(3).map((s) => (
            <ScoreChip key={s.label} label={s.label} val={s.val} color={s.color}
              histValues={hasHist ? s.hist : undefined} />
          ))}
        </div>
        {t.top_drivers && (
          <p className="text-[12px] text-slate-500 mt-2.5 leading-relaxed">{t.top_drivers}</p>
        )}
      </div>

      {/* Core indicators — 2-col grid */}
      <div>
        <div className="label-caps mb-2.5">Indicators</div>
        <div className="grid grid-cols-2 gap-2">
          <IndicatorTile
            label="RSI (14)"
            value={rsi.toFixed(0)}
            valueColor={rsi > 70 ? "#f87171" : rsi < 30 ? "#fbbf24" : "rgb(226 232 240)"}
            sub={rsi > 70 ? "Overbought" : rsi < 30 ? "Oversold" : "Neutral"}
          />
          <IndicatorTile
            label="Stoch K / D"
            value={`${stochK.toFixed(0)} / ${stochD.toFixed(0)}`}
            valueColor={stochK > 80 ? "#f87171" : stochK < 20 ? "#fbbf24" : "rgb(226 232 240)"}
          />
          <IndicatorTile
            label="MACD"
            value={t.macd_cross === "none" ? "Neutral" : (t.macd_cross ?? "—")}
            valueColor={t.macd_cross === "bullish" ? "#34d399" : t.macd_cross === "bearish" ? "#f87171" : "rgb(148 163 184)"}
          />
          <IndicatorTile
            label="BB %B"
            value={`${bbPctB.toFixed(2)}${squeeze ? "  ⊗" : ""}`}
            valueColor={bbPctB > 0.9 ? "#f87171" : bbPctB < 0.1 ? "#fbbf24" : "rgb(226 232 240)"}
            sub={squeeze ? "Squeeze" : undefined}
          />
          <IndicatorTile
            label="Vol σ (1yr)"
            value={`${vol.toFixed(0)}%`}
          />
          <IndicatorTile
            label="Vol / Avg"
            value={`${volRatio.toFixed(1)}×`}
            valueColor={
              t.vol_spike_type === "bullish" ? "#34d399" :
              t.vol_spike_type === "bearish" ? "#f87171" : "rgb(226 232 240)"
            }
            sub={t.vol_spike_type !== "none" ? t.vol_spike_type : undefined}
          />
          <IndicatorTile
            label="WVF"
            value={`${wvf.toFixed(1)}${wvfBottom ? " ↓" : ""}`}
            valueColor={wvfBottom ? "#34d399" : "rgb(226 232 240)"}
            sub={wvfBottom ? "Bottoming" : undefined}
          />
          <IndicatorTile
            label="Candle"
            value={t.candle_pattern?.replace("_", " ") || "—"}
          />
        </div>
      </div>

      {/* Price levels */}
      <div>
        <div className="label-caps mb-1">Price Levels</div>
        <div
          className="rounded-2xl overflow-hidden px-4"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
        >
          <LevelRow label="Resistance" value={`$${resistance.toFixed(2)}`} color="#f87171" />
          <LevelRow label="Support"    value={`$${support.toFixed(2)}`}    color="#34d399" />
          <LevelRow label="SMA 20"     value={`$${sma20.toFixed(2)}`}      color={close > sma20 ? "#34d399" : "#f87171"} />
          <LevelRow label="SMA 50"     value={`$${sma50.toFixed(2)}`}      color={close > sma50 ? "#34d399" : "#f87171"} />
          <LevelRow label="SMA 200"    value={sma200 > 0 ? `$${sma200.toFixed(2)}` : "—"} color={close > sma200 ? "#34d399" : "#f87171"} />
          <div className="flex items-center justify-between py-2.5">
            <span className="text-[13px] text-slate-400">Fib 0.618</span>
            <span className="text-[13px] font-semibold tabular-nums text-slate-300">${Number(t.fib_0618).toFixed(2)}</span>
          </div>
        </div>
      </div>

      {/* Divergence */}
      {t.divergence && t.divergence !== "none" && (
        <div
          className="flex items-center gap-2 rounded-2xl px-4 py-3 text-sm"
          style={{
            background: t.divergence === "bullish" ? "rgba(52,211,153,0.08)" : "rgba(248,113,113,0.08)",
            border: `1px solid ${t.divergence === "bullish" ? "rgba(52,211,153,0.2)" : "rgba(248,113,113,0.2)"}`,
            color: t.divergence === "bullish" ? "#34d399" : "#f87171",
          }}
        >
          <BarChart2 size={14} />
          <span className="font-semibold capitalize">{t.divergence} divergence</span>
          <span className="text-slate-500 text-xs">price vs RSI (20d)</span>
        </div>
      )}
    </div>
  );
}

// ─── Main StockDetail overlay ────────────────────────────────────────────────
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
  const taRef    = useRef<HTMLDivElement>(null);
  const touchRef = useRef<{ startX: number; startY: number; moving: boolean }>({ startX: 0, startY: 0, moving: false });
  const [dragX, setDragX] = useState(0);

  const prefix = currency === "SGD" ? "S$" : "$";
  const upl    = position ? Number(position.upl) : 0;
  const isUp   = upl >= 0;
  const avgCost = position ? Number(position.avg_cost) : 0;
  const uplPct  = avgCost > 0 ? ((Number(position?.last) - avgCost) / avgCost) * 100 : 0;
  const { sector, emoji } = sectorFor(ticker);

  // Swipe-right-to-close
  const onTouchStart = (e: React.TouchEvent) => {
    touchRef.current = { startX: e.touches[0].clientX, startY: e.touches[0].clientY, moving: false };
  };
  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchRef.current.startX;
    const dy = e.touches[0].clientY - touchRef.current.startY;
    if (!touchRef.current.moving) {
      if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < 10 || dx <= 0) return;
      touchRef.current.moving = true;
    }
    if (dx > 0) setDragX(dx);
  };
  const onTouchEnd = () => {
    if (touchRef.current.moving && dragX > 80) onClose();
    else setDragX(0);
    touchRef.current.moving = false;
  };

  // TradingView widgets
  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.innerHTML = "";
      const s = document.createElement("script");
      s.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
      s.async = true;
      s.innerHTML = JSON.stringify({
        autosize: true, symbol: ticker, interval: "D",
        timezone: "Asia/Singapore", theme: "dark", style: "1", locale: "en",
        backgroundColor: "rgba(0,0,0,0)", gridColor: "rgba(255,255,255,0.03)",
        hide_top_toolbar: false, hide_legend: false, allow_symbol_change: false,
        save_image: false, calendar: false, hide_volume: false,
        support_host: "https://www.tradingview.com",
        studies: ["STD;SMA", "STD;EMA", "STD;RSI", "STD;MACD"],
      });
      chartRef.current.appendChild(s);
    }
    if (taRef.current) {
      taRef.current.innerHTML = "";
      const ta = document.createElement("script");
      ta.src = "https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js";
      ta.async = true;
      ta.innerHTML = JSON.stringify({
        colorTheme: "dark", displayMode: "multiple", isTransparent: true,
        locale: "en", interval: "1D", disableInterval: false,
        width: "100%", height: 450, symbol: ticker, showIntervalTabs: true,
      });
      taRef.current.appendChild(ta);
    }
  }, [ticker]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{
        background: "#07090f",
        transform: `translateX(${dragX}px)`,
        transition: touchRef.current.moving ? "none" : "transform 0.25s cubic-bezier(0.4,0,0.2,1)",
        opacity: 1 - Math.min(dragX / 400, 0.25),
      }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {/* ── Header ── */}
      <div
        className="flex items-center justify-between px-4 pt-safe-top"
        style={{
          paddingTop: `calc(var(--safe-top) + 12px)`,
          paddingBottom: 12,
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          background: "rgba(7,9,15,0.9)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
        }}
      >
        <button
          onClick={onClose}
          className="flex items-center gap-1 py-1 pr-2 active:opacity-60"
          style={{ color: "rgb(var(--accent-rgb))" }}
        >
          <ChevronLeft size={20} />
          <span className="text-sm font-medium">Back</span>
        </button>

        <div className="flex items-center gap-2.5 text-center">
          <span className="text-xl">{emoji}</span>
          <div>
            <h2 className="text-base font-bold text-white leading-tight">{ticker}</h2>
            <p className="text-[11px] text-slate-500">{sector}</p>
          </div>
        </div>

        <button onClick={onClose} className="p-2 rounded-xl active:opacity-60" style={{ color: "rgb(100 116 139)" }}>
          <X size={18} />
        </button>
      </div>

      {/* ── Position price strip ── */}
      {position && (
        <div className="flex items-center gap-3 px-4 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
          <span className="text-2xl font-bold text-white tabular-nums">{fmt(position.last, prefix)}</span>
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-semibold tabular-nums"
            style={{
              background: isUp ? "rgba(52,211,153,0.12)" : "rgba(248,113,113,0.12)",
              color: isUp ? "#34d399" : "#f87171",
            }}
          >
            {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {uplPct >= 0 ? "+" : ""}{uplPct.toFixed(2)}%
          </span>
          <span className="text-xs text-slate-500 ml-auto tabular-nums">
            {Number(position.qty).toFixed(0)} @ {fmt(position.avg_cost, prefix)}
          </span>
        </div>
      )}

      {/* ── Decision summary strip ── */}
      {decision && (
        <div className="px-4 py-4" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
          <p className="text-[15px] text-slate-200 leading-relaxed mb-3">{decision.thesis_1liner}</p>
          <div className="flex flex-wrap gap-2">
            {decision.bucket && (
              <span
                className="text-[11px] font-semibold uppercase px-2.5 py-1 rounded-lg"
                style={{ background: "rgba(var(--accent-rgb),0.12)", color: "rgb(var(--accent-rgb))" }}
              >
                {decision.bucket}
              </span>
            )}
            {decision.entry && (
              <span
                className="text-[11px] px-2.5 py-1 rounded-lg"
                style={{ background: "rgba(255,255,255,0.05)", color: "rgb(148 163 184)" }}
              >
                Entry <span className="text-white font-semibold">{fmt(decision.entry, prefix)}</span>
              </span>
            )}
            {decision.target && (
              <span
                className="text-[11px] px-2.5 py-1 rounded-lg"
                style={{ background: "rgba(255,255,255,0.05)", color: "rgb(148 163 184)" }}
              >
                Target <span className="font-semibold" style={{ color: "#34d399" }}>{fmt(decision.target, prefix)}</span>
              </span>
            )}
            {decision.conv && Number(decision.conv) > 0 && (
              <span
                className="text-[11px] px-2.5 py-1 rounded-lg"
                style={{ background: "rgba(255,255,255,0.05)", color: "rgb(148 163 184)" }}
              >
                Conv <span className="text-amber-400 font-semibold">{Math.round(Number(decision.conv))}/5</span>
              </span>
            )}
          </div>
          {decision.thesis && decision.thesis.trim() !== "" && (
            <div className="mt-4 pt-4" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
              <div className="flex items-center justify-between mb-2">
                <span className="label-caps">Thesis</span>
                {decision.thesis_confidence && (
                  <span className="text-[11px] text-slate-500 tabular-nums">
                    Confidence <span className="text-slate-300 font-semibold">{Math.round((Number(decision.thesis_confidence) || 0) * 100)}%</span>
                  </span>
                )}
              </div>
              <p className="text-[13px] text-slate-400 leading-relaxed">{decision.thesis}</p>
            </div>
          )}
        </div>
      )}

      {/* ── Position stats strip ── */}
      {position && (
        <div className="grid grid-cols-4 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
          {[
            { label: "Mkt Val",   value: fmt(position.mkt_val, prefix) },
            { label: "UPL",       value: fmt(position.upl, prefix) },
            { label: "Avg Cost",  value: fmt(position.avg_cost, prefix) },
            { label: "Weight",    value: `${(Number(position.weight) * 100).toFixed(1)}%` },
          ].map((s) => (
            <div key={s.label} className="text-center py-3" style={{ borderRight: "1px solid rgba(255,255,255,0.04)" }}>
              <div className="label-caps mb-0.5">{s.label}</div>
              <div className="text-xs font-semibold text-slate-200 tabular-nums">{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* ── Scrollable body ── */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {exitPlan && <ExitPlanPanel plan={exitPlan} />}
        {techScore && <TechAnalysisPanel techScore={techScore} techHistory={techHistory} ticker={ticker} />}

        {/* TradingView chart */}
        <div className="px-4 pt-5 pb-2">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-base">📈</span>
            <span className="text-[15px] font-semibold text-slate-200">Chart</span>
          </div>
        </div>
        <div className="h-[55vh] min-h-[300px]" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          <div ref={chartRef} className="tradingview-widget-container h-full w-full" />
        </div>

        {/* TradingView TA widget */}
        <div className="px-4 pt-5 pb-2">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-base">🧭</span>
            <span className="text-[15px] font-semibold text-slate-200">Technical Analysis</span>
          </div>
          <p className="text-[12px] text-slate-500 leading-relaxed">
            Real-time MA + oscillator rating. Switch intervals for short vs long-term bias.{" "}
            <span style={{ color: "#34d399" }}>Buy</span> = majority bullish;{" "}
            <span style={{ color: "#f87171" }}>Sell</span> = majority bearish.
          </p>
        </div>
        <div className="px-2 pb-8">
          <div ref={taRef} className="tradingview-widget-container w-full" />
        </div>
      </div>
    </div>,
    document.body
  );
}
