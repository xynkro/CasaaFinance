import type { GexRegimeRow } from "../data";
import { Card } from "./Card";
import { Activity } from "lucide-react";

function num(v?: string): number {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
}

function fmtLevel(v?: string): string {
  const n = num(v);
  return n > 0 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—";
}

function bn(v?: string): string {
  const n = num(v) / 1e9;
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}$bn`;
}

// POSITIVE_PINNED = vol suppressed (good for premium sellers) → green.
// NEGATIVE_TREND  = gap risk → red. NEUTRAL → slate.
function regimeStyle(regime?: string): { chip: string; label: string } {
  switch (regime) {
    case "POSITIVE_PINNED":
      return { chip: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30", label: "PINNED" };
    case "NEGATIVE_TREND":
      return { chip: "text-rose-300 bg-rose-500/15 border-rose-500/30", label: "TREND" };
    default:
      return { chip: "text-slate-400 bg-slate-500/10 border-slate-500/20", label: "NEUTRAL" };
  }
}

function GateBadge({ gate }: { gate?: string }) {
  if (!gate || gate === "NORMAL") return null;
  const ok = gate === "SELL_OK";
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${
        ok
          ? "text-emerald-300 bg-emerald-500/15 border-emerald-500/30"
          : "text-amber-300 bg-amber-500/15 border-amber-500/30"
      }`}
    >
      {ok ? "SELL OK" : "SELL CAUTION"}
    </span>
  );
}

function SymbolRow({ row }: { row: GexRegimeRow }) {
  const s = regimeStyle(row.regime);
  const spot = num(row.spot);
  const flip = num(row.gamma_flip);
  const rel = num(row.flip_distance_pct);
  return (
    <div className="flex flex-col gap-1 py-2 first:pt-0 last:pb-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[length:var(--t-sm)] font-bold text-white">{row.symbol}</span>
        <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${s.chip}`}>
          {s.label}
        </span>
        <GateBadge gate={row.premium_gate} />
        <span className="text-[length:var(--t-2xs)] text-slate-400 tabular-nums">
          {spot > 0 && `${spot.toLocaleString(undefined, { maximumFractionDigits: 0 })} · `}
          net {bn(row.net_gex)}
        </span>
      </div>
      <div className="flex items-center gap-3 text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
        {flip > 0 && (
          <span>
            flip <span className="text-slate-300">{fmtLevel(row.gamma_flip)}</span>
            {rel !== 0 && (
              <span className={rel >= 0 ? "text-emerald-500/70" : "text-rose-500/70"}>
                {" "}({rel >= 0 ? "+" : ""}{rel.toFixed(1)}%)
              </span>
            )}
          </span>
        )}
        <span>
          call wall <span className="text-rose-300/80">{fmtLevel(row.call_wall)}</span>
        </span>
        <span>
          put wall <span className="text-emerald-300/80">{fmtLevel(row.put_wall)}</span>
        </span>
      </div>
    </div>
  );
}

export function GexRegimeBanner({ rows }: { rows: GexRegimeRow[] }) {
  if (!rows.length) return null;
  // Prefer SPY first, then QQQ, then anything else.
  const order = (r: GexRegimeRow) => (r.symbol === "SPY" ? 0 : r.symbol === "QQQ" ? 1 : 2);
  const sorted = [...rows].sort((a, b) => order(a) - order(b));
  const spy = sorted.find((r) => r.symbol === "SPY");

  return (
    <Card>
      <div className="flex items-center gap-2 mb-1.5">
        <Activity size={14} className="text-amber-400" />
        <span className="text-[length:var(--t-xs)] font-semibold text-slate-300 uppercase tracking-wide">
          Gamma Regime
        </span>
        <span className="text-[length:var(--t-2xs)] text-slate-600">dealer positioning · pre-market</span>
      </div>
      <div className="divide-y divide-white/5">
        {sorted.map((r) => (
          <SymbolRow key={r.symbol} row={r} />
        ))}
      </div>
      {spy?.note && (
        <p className="mt-2 pt-2 border-t border-white/5 text-[length:var(--t-2xs)] text-slate-500 leading-relaxed">
          {spy.note}
        </p>
      )}
    </Card>
  );
}
