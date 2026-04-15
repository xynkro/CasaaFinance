import type { SnapshotRow } from "../data";
import { Card } from "./Card";
import { TrendingUp, TrendingDown, Wallet } from "lucide-react";

function fmt(v: string | undefined, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(v: string | undefined): { text: string; positive: boolean } {
  const n = Number(v);
  if (isNaN(n)) return { text: "—", positive: true };
  return {
    text: `${n >= 0 ? "+" : ""}${(n * 100).toFixed(2)}%`,
    positive: n >= 0,
  };
}

function Skeleton() {
  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="shimmer h-4 w-16" />
        <div className="shimmer h-3 w-20" />
      </div>
      <div className="shimmer h-8 w-36 mb-2" />
      <div className="flex gap-4">
        <div className="shimmer h-3 w-24" />
        <div className="shimmer h-3 w-20" />
      </div>
    </Card>
  );
}

export function PnlCard({
  label,
  currency,
  snapshot,
  loading,
}: {
  label: string;
  currency: "USD" | "SGD";
  snapshot: SnapshotRow | null;
  loading?: boolean;
}) {
  if (loading) return <Skeleton />;

  if (!snapshot) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Wallet size={16} />
          <span className="text-sm">{label} — no data yet</span>
        </div>
      </Card>
    );
  }

  const prefix = currency === "SGD" ? "S$" : "$";
  const uplPct = pct(snapshot.upl_pct);
  const Icon = uplPct.positive ? TrendingUp : TrendingDown;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${uplPct.positive ? "bg-emerald-400" : "bg-red-400"}`} />
          <h2 className="text-sm font-medium text-slate-400">{label}</h2>
        </div>
        <time className="text-xs text-slate-500 tabular-nums">{snapshot.date}</time>
      </div>

      <div className="flex items-baseline gap-3 mb-3">
        <span className="text-2xl font-bold text-white tracking-tight tabular-nums">
          {fmt(snapshot.net_liq, prefix)}
        </span>
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold tabular-nums ${
            uplPct.positive
              ? "bg-emerald-500/15 text-emerald-400"
              : "bg-red-500/15 text-red-400"
          }`}
        >
          <Icon size={12} />
          {uplPct.text}
        </span>
      </div>

      <div className="flex gap-5 text-xs text-slate-400">
        <div>
          <span className="text-slate-500">Cash </span>
          <span className="text-slate-300 tabular-nums">{fmt(snapshot.cash, prefix)}</span>
        </div>
        <div>
          <span className="text-slate-500">UPL </span>
          <span className={`tabular-nums ${uplPct.positive ? "text-emerald-400/80" : "text-red-400/80"}`}>
            {fmt(snapshot.upl, prefix)}
          </span>
        </div>
      </div>
    </Card>
  );
}
