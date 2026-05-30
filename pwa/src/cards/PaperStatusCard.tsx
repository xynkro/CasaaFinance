import type { AlpacaSnapshotRow, AlpacaPositionRow } from "../data";
import { FlaskConical, ChevronRight, TrendingUp, TrendingDown } from "lucide-react";

/**
 * Compact paper auto-trader status for the Home dashboard. Clearly marked PAPER
 * and visually distinct (amber, dashed) so it can never be read as real money,
 * and never folded into real net worth. Taps through to Portfolio → Paper.
 * Renders nothing until the bot has an account/positions (no empty stub).
 */
export function PaperStatusCard({
  snapshot,
  positions,
  onOpen,
}: {
  snapshot: AlpacaSnapshotRow | null;
  positions: AlpacaPositionRow[];
  onOpen?: () => void;
}) {
  if (!snapshot && positions.length === 0) return null;

  const upl = positions.reduce((s, p) => s + (Number(p.upl) || 0), 0);
  const nlv = Number(snapshot?.net_liq) || 0;
  const positive = upl >= 0;
  const money = (n: number) =>
    `$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

  return (
    <button
      onClick={onOpen}
      className="w-full text-left rounded-2xl border border-dashed border-amber-500/30 bg-amber-500/[0.06] px-3.5 py-3 flex items-center gap-3 transition-transform active:scale-[0.99]"
    >
      <FlaskConical size={16} className="text-amber-400 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[length:var(--t-xs)] font-bold text-amber-300">Paper Auto-Trader</span>
          <span className="text-[8px] font-bold text-amber-400/70 border border-amber-500/30 rounded px-1 py-px tracking-[0.15em]">
            PAPER
          </span>
        </div>
        <div className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums mt-0.5">
          {positions.length} open · NLV {money(nlv)}
        </div>
      </div>
      <div
        className={`text-[length:var(--t-sm)] font-bold tabular-nums flex items-center gap-1 ${
          positive ? "text-emerald-400" : "text-red-400"
        }`}
      >
        {positive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
        {upl >= 0 ? "+" : "-"}{money(upl)}
      </div>
      <ChevronRight size={14} className="text-slate-600 shrink-0" />
    </button>
  );
}
