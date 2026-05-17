import type { GovConfluenceRow, CongressTradeRow, InsiderSummary } from "../data";
import { GovConfluenceCard } from "../cards/GovConfluenceCard";
import { CongressTradesCard } from "../cards/CongressTradesCard";
import { Card } from "../cards/Card";
import { Eye, TrendingUp } from "lucide-react";

function InsiderFlowCard({ insiderByTicker }: { insiderByTicker: Map<string, InsiderSummary> }) {
  const entries = [...insiderByTicker.entries()]
    .filter(([, s]) => s.net_buy_value > 0)
    .sort((a, b) => b[1].net_buy_value - a[1].net_buy_value)
    .slice(0, 10);

  if (!entries.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Eye size={14} className="text-indigo-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Insider Buys</h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          No significant insider buying detected (last 7 days).
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Eye size={14} className="text-indigo-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Insider Buys</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-500">
          {entries.length} tickers with net buying
        </span>
      </div>
      <div>
        {entries.map(([ticker, summary]) => (
          <div key={ticker} className="flex items-center gap-2 py-2 border-b border-white/3 last:border-0">
            <TrendingUp size={11} className="text-emerald-400 shrink-0" />
            <span className="font-bold text-[length:var(--t-sm)]">{ticker}</span>
            <span className="text-[length:var(--t-xs)] text-emerald-400 ml-auto tabular-nums">
              +${(summary.net_buy_value / 1000).toFixed(0)}K
            </span>
            <span className="text-[length:var(--t-2xs)] text-slate-500">
              {summary.buy_count} buy{summary.buy_count !== 1 ? "s" : ""}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function InsiderPage({
  govConfluence,
  congressTrades,
  insiderByTicker,
  loading,
}: {
  govConfluence: GovConfluenceRow[];
  congressTrades: CongressTradeRow[];
  insiderByTicker: Map<string, InsiderSummary>;
  loading: boolean;
}) {
  if (loading && !govConfluence.length && !congressTrades.length) {
    return <div className="px-4 py-8 text-center text-slate-500 text-[length:var(--t-sm)]">Loading…</div>;
  }

  return (
    <div className="flex flex-col px-4 pb-4">
      <div className="fade-up fade-up-1 mt-3">
        <GovConfluenceCard signals={govConfluence} />
      </div>
      <div className="fade-up fade-up-2 mt-3">
        <CongressTradesCard trades={congressTrades} />
      </div>
      <div className="fade-up fade-up-3 mt-3">
        <InsiderFlowCard insiderByTicker={insiderByTicker} />
      </div>
    </div>
  );
}
