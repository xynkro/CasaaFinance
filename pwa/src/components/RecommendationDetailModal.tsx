import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { OptionRecommendationRow, TechnicalScoreRow } from "../data";
import { X, ChevronLeft, TrendingUp, TrendingDown, Activity, Target, Calendar, Zap } from "lucide-react";

const STRATEGY_LABEL: Record<string, string> = {
  CSP: "Cash-Secured Put",
  CC: "Covered Call",
  LONG_CALL: "Long Call",
  LONG_PUT: "Long Put",
  PMCC: "Poor Man's Covered Call",
};

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: string | number): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

function MetricRow({ label, value, valueColor }: { label: string; value: string | number; valueColor?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-white/5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-semibold tabular-nums ${valueColor ?? "text-slate-200"}`}>
        {value}
      </span>
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  // Score is a number, can be -20 to +20 ish in technical_scores
  const clamped = Math.max(-20, Math.min(20, score));
  const pct = ((clamped + 20) / 40) * 100;  // map to 0-100
  const isPositive = score >= 5;
  const isNegative = score <= -5;
  const color = isPositive ? "bg-emerald-400" : isNegative ? "bg-red-400" : "bg-amber-400";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</span>
        <span className={`text-xs font-bold tabular-nums ${isPositive ? "text-emerald-400" : isNegative ? "text-red-400" : "text-amber-400"}`}>
          {score > 0 ? "+" : ""}{score.toFixed(1)}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-white/5 overflow-hidden relative">
        <div className="absolute top-0 left-1/2 w-px h-full bg-white/20" />
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function parseDrivers(top_drivers: string): { label: string; drivers: string[] }[] {
  // Format: "BUY: +MACD,−Fib position,+Trend | CSP: −Fib,+MACD | CC: +Fib,+Stoch"
  if (!top_drivers) return [];
  return top_drivers.split("|").map((part) => {
    const [label, rest] = part.split(":").map((s) => s.trim());
    const drivers = (rest ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    return { label, drivers };
  });
}

export function RecommendationDetailModal({
  rec,
  techScore,
  onClose,
}: {
  rec: OptionRecommendationRow;
  techScore?: TechnicalScoreRow | null;
  onClose: () => void;
}) {
  // Lock body scroll while modal is open
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  // Slide-in-from-right entry animation. Start off-screen, then transition
  // on mount via requestAnimationFrame for a smooth GPU-accelerated slide.
  const [entering, setEntering] = useState(true);
  useEffect(() => {
    const id = requestAnimationFrame(() => setEntering(false));
    return () => cancelAnimationFrame(id);
  }, []);

  // Right-swipe to close (matches WSR Lite modal pattern)
  const touchRef = useRef<{ startX: number; startY: number; moving: boolean }>({
    startX: 0, startY: 0, moving: false,
  });
  const [dragX, setDragX] = useState(0);
  const SWIPE_THRESHOLD = 80;
  const onTouchStart = (e: React.TouchEvent) => {
    touchRef.current = { startX: e.touches[0].clientX, startY: e.touches[0].clientY, moving: false };
  };
  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchRef.current.startX;
    const dy = e.touches[0].clientY - touchRef.current.startY;
    if (!touchRef.current.moving) {
      if (Math.abs(dy) > Math.abs(dx)) return;
      if (Math.abs(dx) < 10 || dx <= 0) return;
      touchRef.current.moving = true;
    }
    if (touchRef.current.moving && dx > 0) setDragX(dx);
  };
  const onTouchEnd = () => {
    if (touchRef.current.moving && dragX > SWIPE_THRESHOLD) onClose();
    else setDragX(0);
    touchRef.current.moving = false;
  };

  const strategy = STRATEGY_LABEL[rec.strategy] ?? rec.strategy;
  const accountLabel = rec.account === "caspar" ? "Caspar" : "Sarah";
  const accountColor = rec.account === "caspar" ? "text-blue-400" : "text-pink-400";

  const strike = Number(rec.strike);
  const yld = Number(rec.annual_yield_pct);
  const ivRank = Number(rec.iv_rank);
  const conf = Number(rec.thesis_confidence) || 0;

  // Pull current price + key tech indicators from technicalScores if available
  const close = techScore ? Number(techScore.close) : null;
  const rsi = techScore ? Number(techScore.rsi_14) : null;
  const macdHist = techScore ? Number(techScore.macd_hist) : null;
  const macdCross = techScore?.macd_cross;
  const sma20 = techScore ? Number(techScore.sma_20) : null;
  const sma50 = techScore ? Number(techScore.sma_50) : null;
  const sma200 = techScore ? Number(techScore.sma_200) : null;
  const support = techScore ? Number(techScore.support) : null;
  const resistance = techScore ? Number(techScore.resistance) : null;
  const trend = techScore?.trend;
  const candle = techScore?.candle_pattern;
  const volRegime = techScore?.vol_regime;
  const earningsDays = techScore?.earnings_days_away ? Number(techScore.earnings_days_away) : null;
  const entrySignal = techScore?.entry_exit_signal;

  const scoreCsp  = techScore ? Number(techScore.score_csp) : null;
  const scoreCc   = techScore ? Number(techScore.score_cc) : null;
  const scoreBuy  = techScore ? Number(techScore.score_buy) : null;
  const scoreLC   = techScore ? Number(techScore.score_long_call) : null;
  const scoreLP   = techScore ? Number(techScore.score_long_put) : null;

  const driverGroups = techScore?.top_drivers ? parseDrivers(techScore.top_drivers) : [];

  // Compute distance from strike for context
  const otmPct = close != null ? ((rec.right === "P" ? close - strike : strike - close) / close * 100) : null;

  // Format expiry
  let expiryDisplay = rec.expiry;
  if (rec.expiry.length === 8 && /^\d+$/.test(rec.expiry)) {
    expiryDisplay = `${rec.expiry.slice(4, 6)}/${rec.expiry.slice(6, 8)}/${rec.expiry.slice(0, 4)}`;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[#050916]"
      style={{
        // On mount: start at +100vw (off-screen-right), then transition to 0.
        // After mount: drag transform takes over.
        transform: entering
          ? "translateX(100%)"
          : `translateX(${dragX}px)`,
        transition: touchRef.current.moving
          ? "none"
          : "transform 280ms cubic-bezier(0.32, 0.72, 0, 1)",
        opacity: 1 - Math.min(dragX / 400, 0.3),
        willChange: "transform",
      }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {/* Header — back button (left) + close (right). NO backdrop click-to-close */}
      <div className="flex items-center justify-between px-3 py-3 pt-safe-top border-b border-white/6">
        <button
          onClick={onClose}
          className="flex items-center gap-1 pr-2 py-2 text-indigo-400 active:text-indigo-300"
          aria-label="Back"
          style={{ touchAction: "manipulation", WebkitTapHighlightColor: "transparent" }}
        >
          <ChevronLeft size={20} />
          <span className="text-sm">Back</span>
        </button>
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-emerald-400" />
          <div className="text-right">
            <h2 className="text-base font-bold text-white leading-tight">{rec.ticker}</h2>
            <span className="text-[10px] text-slate-400 font-mono tabular-nums">
              ${strike.toFixed(strike < 10 ? 2 : 0)}{rec.right} · {expiryDisplay}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-400 active:text-white"
          aria-label="Close"
          style={{ touchAction: "manipulation", WebkitTapHighlightColor: "transparent" }}
        >
          <X size={18} />
        </button>
      </div>

      {/* Strategy + account band */}
      <div className="px-4 py-3 border-b border-white/6 flex items-center gap-3">
        <span className="text-xs text-indigo-400 font-medium">{strategy}</span>
        <span className="text-slate-700">·</span>
        <span className={`text-[11px] font-semibold uppercase tracking-wider ${accountColor}`}>{accountLabel}</span>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-5 py-5 space-y-5">
          {/* Quick stats row */}
          <div className="grid grid-cols-3 gap-2 mt-2">
            <div className="rounded-lg p-3 border border-emerald-500/20 bg-emerald-500/5">
              <div className="text-[9px] uppercase tracking-wider text-emerald-500 font-bold mb-1">Yield</div>
              <div className="text-lg font-bold text-emerald-400 tabular-nums">{fmtPct(yld)}</div>
              <div className="text-[9px] text-slate-500">/year</div>
            </div>
            <div className="rounded-lg p-3 border border-white/5 bg-white/5">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-1">Confidence</div>
              <div className="text-lg font-bold text-slate-200 tabular-nums">{Math.round(conf * 100)}%</div>
              <div className="text-[9px] text-slate-500">thesis</div>
            </div>
            <div className="rounded-lg p-3 border border-white/5 bg-white/5">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-1">Cash</div>
              <div className="text-lg font-bold text-slate-200 tabular-nums">{fmt(rec.cash_required, "$")}</div>
              <div className="text-[9px] text-slate-500">required</div>
            </div>
          </div>

          {/* Why this position section */}
          <section>
            <h3 className="text-[10px] uppercase tracking-widest text-amber-400 font-bold mb-2 flex items-center gap-1.5">
              <Zap size={11} /> Why this position
            </h3>
            <div className="rounded-lg p-3 bg-white/[0.02] border border-white/5 space-y-2">
              {rec.thesis ? (
                <p className="text-sm text-slate-300 leading-relaxed">{rec.thesis}</p>
              ) : (
                <p className="text-sm text-slate-500 italic">No thesis text recorded.</p>
              )}
              <MetricRow label="Premium per share" value={fmt(rec.premium_per_share)} />
              <MetricRow label="Breakeven" value={fmt(rec.breakeven)} />
              <MetricRow label="Delta (Δ)" value={Number(rec.delta).toFixed(2)} />
              <MetricRow label="IV Rank" value={`${ivRank.toFixed(0)}`} valueColor={ivRank >= 50 ? "text-emerald-400" : ivRank >= 30 ? "text-amber-400" : "text-slate-500"} />
              {otmPct != null && (
                <MetricRow
                  label={`${rec.right === "P" ? "Below" : "Above"} current price`}
                  value={`${otmPct.toFixed(1)}%`}
                  valueColor={otmPct >= 5 ? "text-emerald-400" : "text-amber-400"}
                />
              )}
            </div>
          </section>

          {/* Technical analysis from technical_scores */}
          {techScore ? (
            <section>
              <h3 className="text-[10px] uppercase tracking-widest text-blue-400 font-bold mb-2 flex items-center gap-1.5">
                <Activity size={11} /> Technical Read
              </h3>
              <div className="rounded-lg p-3 bg-white/[0.02] border border-white/5 space-y-1">
                <MetricRow
                  label="Current price"
                  value={close != null ? `$${close.toFixed(2)}` : "—"}
                />
                <MetricRow
                  label="Trend"
                  value={trend ?? "—"}
                  valueColor={trend === "Uptrend" ? "text-emerald-400" : trend === "Downtrend" ? "text-red-400" : "text-amber-400"}
                />
                <MetricRow
                  label="RSI(14)"
                  value={rsi != null ? rsi.toFixed(0) : "—"}
                  valueColor={rsi != null && rsi >= 70 ? "text-red-400" : rsi != null && rsi <= 30 ? "text-emerald-400" : "text-slate-200"}
                />
                <MetricRow
                  label="MACD histogram"
                  value={macdHist != null ? macdHist.toFixed(3) + (macdCross && macdCross !== "none" ? ` (${macdCross})` : "") : "—"}
                  valueColor={macdHist != null && macdHist > 0 ? "text-emerald-400" : macdHist != null && macdHist < 0 ? "text-red-400" : "text-slate-200"}
                />
                {sma20 != null && sma50 != null && sma200 != null && close != null && (
                  <>
                    <MetricRow
                      label="vs SMA50"
                      value={`${(((close - sma50) / sma50) * 100).toFixed(1)}%`}
                      valueColor={close > sma50 ? "text-emerald-400" : "text-red-400"}
                    />
                    <MetricRow
                      label="vs SMA200"
                      value={`${(((close - sma200) / sma200) * 100).toFixed(1)}%`}
                      valueColor={close > sma200 ? "text-emerald-400" : "text-red-400"}
                    />
                  </>
                )}
                {support != null && resistance != null && close != null && (
                  <>
                    <MetricRow
                      label="Support"
                      value={`$${support.toFixed(2)} (${(((close - support) / close) * 100).toFixed(1)}% below)`}
                    />
                    <MetricRow
                      label="Resistance"
                      value={`$${resistance.toFixed(2)} (${(((resistance - close) / close) * 100).toFixed(1)}% above)`}
                    />
                  </>
                )}
                {volRegime && (
                  <MetricRow label="Vol regime" value={volRegime} />
                )}
                {candle && candle !== "none" && (
                  <MetricRow label="Latest candle" value={candle.replace(/_/g, " ")} />
                )}
                {earningsDays != null && earningsDays > 0 && earningsDays <= 30 && (
                  <MetricRow
                    label="Earnings"
                    value={`in ${earningsDays} day${earningsDays === 1 ? "" : "s"}`}
                    valueColor={earningsDays <= 7 ? "text-amber-400" : "text-slate-200"}
                  />
                )}
                {entrySignal && (
                  <MetricRow
                    label="Signal"
                    value={entrySignal}
                    valueColor={entrySignal.includes("BUY") ? "text-emerald-400" : entrySignal.includes("SELL") ? "text-red-400" : "text-slate-200"}
                  />
                )}
              </div>
            </section>
          ) : (
            <section>
              <h3 className="text-[10px] uppercase tracking-widest text-blue-400 font-bold mb-2 flex items-center gap-1.5">
                <Activity size={11} /> Technical Read
              </h3>
              <div className="rounded-lg p-3 bg-white/[0.02] border border-white/5">
                <p className="text-xs text-slate-500 italic">
                  No technical scoring data for {rec.ticker} yet. The Run Strategy Scoring routine
                  populates score_csp / score_cc / RSI / MACD / support&resistance for each watched ticker.
                </p>
              </div>
            </section>
          )}

          {/* Strategy score breakdown */}
          {techScore && (scoreCsp != null || scoreCc != null) && (
            <section>
              <h3 className="text-[10px] uppercase tracking-widest text-indigo-400 font-bold mb-2 flex items-center gap-1.5">
                <Target size={11} /> How Confidence Was Derived
              </h3>
              <div className="rounded-lg p-3 bg-white/[0.02] border border-white/5 space-y-3">
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Each strategy gets a quant score from the same technical inputs. Higher = more
                  favourable setup right now. The recommendation ranks against rule thresholds.
                </p>
                {scoreBuy != null && <ScoreBar label="Buy stock" score={scoreBuy} />}
                {scoreCsp != null && <ScoreBar label="CSP" score={scoreCsp} />}
                {scoreCc != null && <ScoreBar label="CC" score={scoreCc} />}
                {scoreLC != null && <ScoreBar label="Long call" score={scoreLC} />}
                {scoreLP != null && <ScoreBar label="Long put" score={scoreLP} />}
              </div>
            </section>
          )}

          {/* Top drivers — the "why" of each score */}
          {driverGroups.length > 0 && (
            <section>
              <h3 className="text-[10px] uppercase tracking-widest text-purple-400 font-bold mb-2">
                Score Drivers (what's pushing each direction)
              </h3>
              <div className="rounded-lg p-3 bg-white/[0.02] border border-white/5 space-y-2">
                {driverGroups.map((g) => (
                  <div key={g.label}>
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
                      {g.label}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {g.drivers.map((d, i) => {
                        const sign = d[0];
                        const text = d.slice(1).trim();
                        const color = sign === "+" ? "text-emerald-400 border-emerald-500/30 bg-emerald-500/5"
                                    : sign === "−" || sign === "-" ? "text-red-400 border-red-500/30 bg-red-500/5"
                                    : "text-slate-400 border-white/10 bg-white/5";
                        return (
                          <span key={i} className={`px-2 py-0.5 rounded text-[10px] font-medium border ${color}`}>
                            {sign === "+" ? <TrendingUp size={9} className="inline mr-1" /> : <TrendingDown size={9} className="inline mr-1" />}
                            {text}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Source / metadata */}
          {(rec.source || rec.date) && (
            <section>
              <div className="flex items-center justify-between text-[10px] text-slate-600">
                {rec.source && <span>Source: {rec.source}</span>}
                {rec.date && (
                  <span className="flex items-center gap-1">
                    <Calendar size={9} /> {rec.date.slice(0, 10)}
                  </span>
                )}
              </div>
            </section>
          )}
      </div>
    </div>,
    document.body,
  );
}
