import type { PositionRow, MacroRow } from "../data";
import { Card } from "./Card";
import { sectorFor } from "../lib/emojis";

/**
 * Convert a position list in native currency to USD-weighted sector buckets.
 * Uses USD/SGD rate from macro for Sarah's SGD positions.
 */
function bucketize(
  caspar: PositionRow[],
  sarah: PositionRow[],
  usdSgd: number,
): Array<{ sector: string; emoji: string; usd: number; pct: number }> {
  const buckets = new Map<string, { emoji: string; usd: number }>();

  const add = (tickers: PositionRow[], toUsd: (n: number) => number) => {
    for (const p of tickers) {
      const { sector, emoji } = sectorFor(p.ticker);
      const usd = toUsd(Number(p.mkt_val) || 0);
      const prev = buckets.get(sector);
      if (prev) prev.usd += usd;
      else buckets.set(sector, { emoji, usd });
    }
  };

  add(caspar, (n) => n); // already USD
  add(sarah, (n) => (usdSgd > 0 ? n / usdSgd : 0));

  const total = Array.from(buckets.values()).reduce((s, b) => s + b.usd, 0);
  return Array.from(buckets.entries())
    .map(([sector, b]) => ({
      sector,
      emoji: b.emoji,
      usd: b.usd,
      pct: total > 0 ? (b.usd / total) * 100 : 0,
    }))
    .sort((a, b) => b.usd - a.usd);
}

const PALETTE = [
  "bg-indigo-500/70",
  "bg-blue-500/70",
  "bg-violet-500/70",
  "bg-emerald-500/70",
  "bg-amber-500/70",
  "bg-rose-500/70",
  "bg-cyan-500/70",
  "bg-fuchsia-500/70",
  "bg-orange-500/70",
  "bg-teal-500/70",
  "bg-slate-500/70",
];

export function SectorMixCard({
  casparPositions,
  sarahPositions,
  macro,
}: {
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  macro: MacroRow | null;
}) {
  const usdSgd = Number(macro?.usd_sgd) || 0;
  if (casparPositions.length === 0 && sarahPositions.length === 0) return null;

  const buckets = bucketize(casparPositions, sarahPositions, usdSgd);
  if (buckets.length === 0) return null;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-base)]">🏢</span>
          <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Sector Mix</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600">{buckets.length} sectors</span>
      </div>

      {/* Stacked proportion bar */}
      <div className="flex h-2 rounded-full overflow-hidden mb-4">
        {buckets.map((b, i) => (
          <div
            key={b.sector}
            className={`${PALETTE[i % PALETTE.length]} transition-all`}
            style={{ width: `${b.pct}%` }}
            title={`${b.sector} ${b.pct.toFixed(1)}%`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {buckets.map((b, i) => (
          <div key={b.sector} className="flex items-center justify-between gap-2 text-[length:var(--t-xs)]">
            <div className="flex items-center gap-1.5 min-w-0">
              <div className={`w-2 h-2 rounded-sm shrink-0 ${PALETTE[i % PALETTE.length]}`} />
              <span className="text-[length:var(--t-sm)]">{b.emoji}</span>
              <span className="text-slate-300 truncate">{b.sector}</span>
            </div>
            <span className="text-slate-400 tabular-nums font-medium shrink-0">{b.pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
