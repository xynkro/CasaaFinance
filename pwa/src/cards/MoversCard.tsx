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
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-[10px] text-slate-600 tabular-nums w-3">{rank}</span>
        <span className="text-sm">{m.emoji}</span>
        <span className="text-sm font-semibold text-slate-100 tabular-nums">{m.ticker}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`text-xs tabular-nums ${isUp ? "text-emerald-400/80" : "text-red-400/80"}`}>
          {prefix}{Math.abs(m.upl).toLocaleString("en-US", { maximumFractionDigits: 0 })}
        </span>
        <span
          className={`inline-flex items-center gap-0.5 text-xs font-semibold tabular-nums px-1.5 py-0.5 rounded ${
            isUp ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
          }`}
        >
          {isUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
          {isUp ? "+" : ""}{m.pct.toFixed(1)}%
        </span>
      </div>
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
  const winners = sorted.slice(0, 3);
  const losers = sorted.slice(-3).reverse();

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🏆</span>
          <h2 className="text-sm font-semibold text-slate-200">Top Movers</h2>
        </div>
        <span className="text-[10px] text-slate-600">{movers.length} holdings</span>
      </div>

      <div className="grid grid-cols-2 gap-x-5">
        <div>
          <div className="text-[10px] uppercase tracking-wider font-semibold text-emerald-400/70 mb-1">
            📈 Winners
          </div>
          <div className="divide-y divide-white/5">
            {winners.map((m, i) => <Row key={m.ticker + m.ccy} m={m} rank={i + 1} />)}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider font-semibold text-red-400/70 mb-1">
            📉 Losers
          </div>
          <div className="divide-y divide-white/5">
            {losers.map((m, i) => <Row key={m.ticker + m.ccy + "l"} m={m} rank={i + 1} />)}
          </div>
        </div>
      </div>
    </Card>
  );
}
