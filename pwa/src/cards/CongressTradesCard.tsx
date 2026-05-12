import { useState } from "react";
import type { CongressTradeRow } from "../data";
import { Card } from "./Card";
import { Users, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from "lucide-react";

function fmtAmount(min: string, max: string): string {
  const lo = Number(min);
  const hi = Number(max);
  if (isNaN(lo) && isNaN(hi)) return "—";
  const fmt = (n: number) => {
    if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
    return `$${n.toFixed(0)}`;
  };
  if (isNaN(lo)) return fmt(hi);
  if (isNaN(hi) || lo === hi) return fmt(lo);
  return `${fmt(lo)}–${fmt(hi)}`;
}

function fmtDate(d: string): string {
  if (!d || d.length < 10) return "—";
  return `${d.slice(5, 7)}/${d.slice(8, 10)}`;
}

function TradeRow({ row }: { row: CongressTradeRow }) {
  const isBuy = row.transaction_type?.toLowerCase() === "buy";
  return (
    <div className="flex items-center gap-2 py-2 border-b border-white/3 last:border-0">
      {isBuy ? (
        <TrendingUp size={11} className="text-emerald-400 shrink-0" />
      ) : (
        <TrendingDown size={11} className="text-red-400 shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker}</span>
          <span className={`text-[length:var(--t-2xs)] font-semibold uppercase ${isBuy ? "text-emerald-400" : "text-red-400"}`}>
            {row.transaction_type}
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
            {fmtAmount(row.amount_min, row.amount_max)}
          </span>
        </div>
        <div className="flex items-center gap-1 text-[length:var(--t-2xs)] text-slate-500">
          <span className="truncate">{row.politician_name}</span>
          <span className={row.party?.[0] === "D" ? "text-blue-400" : row.party?.[0] === "R" ? "text-red-400" : ""}>
            ({row.party?.[0] || "?"})
          </span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-600">{row.chamber}</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-600 tabular-nums">{fmtDate(row.transaction_date)}</span>
        </div>
      </div>
    </div>
  );
}

export function CongressTradesCard({ trades }: { trades: CongressTradeRow[] }) {
  const [showAll, setShowAll] = useState(false);

  if (!trades.length) return null;

  const buys = trades.filter((t) => t.transaction_type?.toLowerCase() === "buy");
  const sells = trades.filter((t) => t.transaction_type?.toLowerCase() !== "buy");
  const display = showAll ? trades : trades.slice(0, 8);
  const hasMore = trades.length > 8;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Users size={14} className="text-amber-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Capitol Trades</h2>
        </div>
        <div className="flex items-center gap-2 text-[length:var(--t-2xs)]">
          <span className="text-emerald-400 tabular-nums">{buys.length} buy</span>
          <span className="text-slate-600">·</span>
          <span className="text-red-400 tabular-nums">{sells.length} sell</span>
        </div>
      </div>

      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-2 leading-relaxed">
        STOCK Act filings last 7 days — tickers with positions or on watchlist.
      </p>

      <div>
        {display.map((t, i) => (
          <TradeRow key={`${t.filing_id}-${i}`} row={t} />
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="flex items-center justify-center gap-1 w-full pt-2 mt-1 border-t border-white/5 text-[length:var(--t-xs)] text-indigo-400 font-medium"
        >
          <span>{showAll ? "Show less" : `Show all ${trades.length}`}</span>
          {showAll ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      )}
    </Card>
  );
}
