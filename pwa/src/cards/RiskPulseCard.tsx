import type { MacroRow } from "../data";
import { Card } from "./Card";
import { vixEmoji } from "../lib/emojis";

/**
 * Risk Pulse — a VIX-driven read-the-room card.
 * Also surfaces 10Y, DXY for the macro-at-a-glance story.
 */
export function RiskPulseCard({ macro }: { macro: MacroRow | null }) {
  if (!macro) return null;

  const vix = Number(macro.vix);
  const pulse = vixEmoji(vix);

  // Gauge position — map VIX to 0..100 for the bar
  const gaugePct = Math.min(100, Math.max(0, ((vix - 10) / 30) * 100));

  const us10y = Number(macro.us_10y);
  const dxy = Number(macro.dxy);
  const spx = Number(macro.spx);

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🌡️</span>
          <h2 className="text-sm font-semibold text-slate-200">Risk Pulse</h2>
        </div>
        <span className={`text-xs font-semibold ${pulse.tone}`}>
          {pulse.emoji} {pulse.label}
        </span>
      </div>

      {/* VIX gauge */}
      <div className="mb-3">
        <div className="flex items-baseline justify-between mb-1.5">
          <span className="text-[10px] text-slate-500 uppercase tracking-wider">VIX</span>
          <span className="text-2xl font-bold text-white tabular-nums">{vix.toFixed(1)}</span>
        </div>
        <div className="relative h-1.5 rounded-full bg-slate-700/40 overflow-hidden">
          {/* Gradient track — green → yellow → red */}
          <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/30 via-yellow-500/30 to-red-500/30" />
          {/* Indicator */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-white shadow-lg transition-all"
            style={{ left: `calc(${gaugePct}% - 5px)` }}
          />
        </div>
        <div className="flex justify-between text-[9px] text-slate-600 mt-1">
          <span>10</span>
          <span>20</span>
          <span>30</span>
          <span>40+</span>
        </div>
      </div>

      {/* Supporting macro */}
      <div className="grid grid-cols-3 gap-2 pt-3 border-t border-white/5">
        <div className="text-center">
          <div className="text-[10px] text-slate-500 uppercase">10Y</div>
          <div className="text-sm font-semibold text-slate-200 tabular-nums">{us10y.toFixed(2)}%</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-slate-500 uppercase">DXY</div>
          <div className="text-sm font-semibold text-slate-200 tabular-nums">{dxy.toFixed(1)}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-slate-500 uppercase">SPX</div>
          <div className="text-sm font-semibold text-slate-200 tabular-nums">
            {spx >= 1000 ? `${(spx / 1000).toFixed(2)}k` : spx.toFixed(0)}
          </div>
        </div>
      </div>
    </Card>
  );
}
