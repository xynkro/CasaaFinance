import type { SnapshotRow, PositionRow } from "../data";
import { Card } from "./Card";
import { TrendingUp, TrendingDown, Wallet } from "lucide-react";

function fmt(v: string | number | undefined, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtCompact(v: string | number | undefined, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n) || n === 0) return "—";
  if (Math.abs(n) >= 1000) {
    return `${prefix}${(n / 1000).toFixed(1)}k`;
  }
  return fmt(v, prefix);
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

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300 tabular-nums">{value}</span>
    </div>
  );
}

export function PnlCard({
  label,
  currency,
  snapshot,
  positions,
  loading,
}: {
  label: string;
  currency: "USD" | "SGD";
  snapshot: SnapshotRow | null;
  positions?: PositionRow[];
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
  const posCount = positions?.length ?? 0;
  const totalMktVal = positions?.reduce((sum, p) => sum + Number(p.mkt_val || 0), 0) ?? 0;

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

      {/* Summary stats grid */}
      <div className="grid grid-cols-2 gap-x-5 gap-y-1.5 text-xs">
        <StatRow label="Cash" value={fmt(snapshot.cash, prefix)} />
        <StatRow label="UPL" value={fmt(snapshot.upl, prefix)} />
        <StatRow label="Market value" value={fmtCompact(totalMktVal, prefix)} />
        <StatRow label="Positions" value={posCount > 0 ? `${posCount} holdings` : "—"} />
      </div>
    </Card>
  );
}
