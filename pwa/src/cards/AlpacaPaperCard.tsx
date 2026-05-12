import type { AlpacaSnapshotRow, AlpacaPositionRow } from "../data";
import { Card } from "./Card";
import { FlaskConical, TrendingUp, TrendingDown } from "lucide-react";

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function PositionRow({ pos }: { pos: AlpacaPositionRow }) {
  const upl = Number(pos.upl);
  const uplPct = Number(pos.upl_pct);
  const positive = upl >= 0;
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/3 last:border-0">
      <div className="flex items-center gap-2">
        {positive ? (
          <TrendingUp size={11} className="text-emerald-400 shrink-0" />
        ) : (
          <TrendingDown size={11} className="text-red-400 shrink-0" />
        )}
        <span className="text-[length:var(--t-sm)] font-bold text-white">{pos.ticker}</span>
        <span className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
          {pos.qty} @ {fmt(pos.avg_cost)}
        </span>
      </div>
      <div className="text-right">
        <div className="text-[length:var(--t-sm)] tabular-nums text-slate-200">{fmt(pos.mkt_val)}</div>
        <div className={`text-[length:var(--t-2xs)] tabular-nums font-semibold ${
          positive ? "text-emerald-400" : "text-red-400"
        }`}>
          {upl >= 0 ? "+" : ""}{fmt(pos.upl)} ({uplPct >= 0 ? "+" : ""}{uplPct.toFixed(1)}%)
        </div>
      </div>
    </div>
  );
}

export function AlpacaPaperCard({
  snapshot,
  positions,
  loading,
}: {
  snapshot: AlpacaSnapshotRow | null;
  positions: AlpacaPositionRow[];
  loading: boolean;
}) {
  if (loading && !snapshot) {
    return (
      <Card>
        <div className="space-y-2">
          <div className="shimmer h-4 w-28" />
          <div className="shimmer h-8 w-40" />
          <div className="shimmer h-4 w-full" />
        </div>
      </Card>
    );
  }

  if (!snapshot && !positions.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <FlaskConical size={16} />
          <span className="text-[length:var(--t-sm)]">
            Alpaca paper account — no data yet. Syncs after each decision execution.
          </span>
        </div>
      </Card>
    );
  }

  const totalUpl = positions.reduce((acc, p) => acc + Number(p.upl), 0);

  return (
    <Card variant="bright">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <FlaskConical size={14} className="text-orange-400" />
          <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Alpaca Paper</h2>
          {snapshot && (
            <time className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">
              {(snapshot.date || "").slice(0, 10)}
            </time>
          )}
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
          {positions.length} position{positions.length !== 1 ? "s" : ""}
        </span>
      </div>

      {snapshot && (
        <div className="grid grid-cols-3 gap-3 mb-3">
          <div>
            <div className="text-[length:var(--t-2xs)] text-slate-600">NLV</div>
            <div className="text-[length:var(--t-sm)] font-bold text-white tabular-nums">{fmt(snapshot.net_liq)}</div>
          </div>
          <div>
            <div className="text-[length:var(--t-2xs)] text-slate-600">Cash</div>
            <div className="text-[length:var(--t-sm)] text-slate-300 tabular-nums">{fmt(snapshot.cash)}</div>
          </div>
          <div>
            <div className="text-[length:var(--t-2xs)] text-slate-600">UPL</div>
            <div className={`text-[length:var(--t-sm)] font-semibold tabular-nums ${
              totalUpl >= 0 ? "text-emerald-400" : "text-red-400"
            }`}>
              {totalUpl >= 0 ? "+" : ""}{fmt(totalUpl)}
            </div>
          </div>
        </div>
      )}

      {positions.length > 0 && (
        <div>
          {positions.map((p) => (
            <PositionRow key={p.ticker} pos={p} />
          ))}
        </div>
      )}
    </Card>
  );
}
