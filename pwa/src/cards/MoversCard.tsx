import type { PositionRow } from "../data";
import { Card } from "./Card";
import { sectorFor } from "../lib/emojis";
import { TrendingUp, TrendingDown } from "lucide-react";

interface Mover {
  ticker: string;
  pct: number;      // UPL % vs avg cost
  upl: number;      // absolute UPL in native ccy
  ccy: "USD" | "SGD";
  emoji: string;
}

function buildMovers(positions: PositionRow[], ccy: "USD" | "SGD"): Mover[] {
  return positions
    .map((p) => {
      const avg = Number(p.avg_cost);
      const last = Number(p.last);
      const pct = avg > 0 ? ((last - avg) / avg) * 100 : 0;
      return {
        ticker: p.ticker,
        pct,
        upl: Number(p.upl),
        ccy,
        emoji: sectorFor(p.ticker).emoji,
      };
    })
    .filter((m) => !isNaN(m.pct));
}

function Row({ m, rank }: { m: Mover; rank: number }) {
  const isUp = m.pct >= 0;
  const prefix = m.ccy === "SGD" ? "S$" : "$";
  return (
    <div className="flex items-center gap-3 py-2.5">
      {/* Rank */}
      <span className="text-[length:var(--t-2xs)] text-slate-600 font-tabular w-3 shrink-0">{rank}</span>
      {/* Sector emoji */}
      <span className="text-[length:var(--t-base)] shrink-0 w-6 text-center">{m.emoji}</span>
      {/* Ticker — sans (it's a label, not a number) */}
      <span className="text-[length:var(--t-sm)] font-semibold text-slate-100 flex-1 min-w-0 truncate">
        {m.ticker}
      </span>
      {/* UPL amount — subtle */}
      <span className={`text-[length:var(--t-xs)] font-tabular shrink-0 ${isUp ? "text-emerald-400/60" : "text-red-400/60"}`}>
        {isUp ? "+" : "−"}{prefix}{Math.abs(m.upl).toLocaleString("en-US", { maximumFractionDigits: 0 })}
      </span>
      {/* Percent chip */}
      <span
        className={`inline-flex items-center gap-0.5 text-[length:var(--t-xs)] font-semibold font-tabular px-2 py-0.5 rounded shrink-0 ${
          isUp ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
        }`}
      >
        {isUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
        {isUp ? "+" : ""}{m.pct.toFixed(1)}%
      </span>
    </div>
  );
}

export function MoversCard({
  casparPositions,
  sarahPositions,
}: {
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
}) {
  const movers: Mover[] = [
    ...buildMovers(casparPositions, "USD"),
    ...buildMovers(sarahPositions, "SGD"),
  ];
  if (movers.length === 0) return null;

  const sorted = [...movers].sort((a, b) => b.pct - a.pct);
  // Up to 3 winners (positive) and 3 losers (negative)
  const winners = sorted.filter((m) => m.pct >= 0).slice(0, 3);
  const losers = sorted.filter((m) => m.pct < 0).slice(-3).reverse();

  return (
    <Card>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-base)]">🏆</span>
          <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Top Movers</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600">{movers.length} holdings</span>
      </div>

      {winners.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 text-[length:var(--t-2xs)] uppercase tracking-wider font-semibold text-emerald-400/70 pt-2">
            <span>📈</span>
            <span>Winners</span>
          </div>
          <div className="divide-y divide-white/5">
            {winners.map((m, i) => <Row key={m.ticker + m.ccy} m={m} rank={i + 1} />)}
          </div>
        </div>
      )}

      {losers.length > 0 && (
        <div className="mt-2">
          <div className="flex items-center gap-1.5 text-[length:var(--t-2xs)] uppercase tracking-wider font-semibold text-red-400/70 pt-2 border-t border-white/5">
            <span>📉</span>
            <span>Losers</span>
          </div>
          <div className="divide-y divide-white/5">
            {losers.map((m, i) => <Row key={m.ticker + m.ccy + "l"} m={m} rank={i + 1} />)}
          </div>
        </div>
      )}
    </Card>
  );
}
