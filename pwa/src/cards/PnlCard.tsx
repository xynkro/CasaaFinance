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
  if (Math.abs(n) >= 1000) return `${prefix}${(n / 1000).toFixed(1)}k`;
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
      <div className="flex items-center justify-between mb-4">
        <div className="shimmer h-3.5 w-16 rounded" />
        <div className="shimmer h-3 w-20 rounded" />
      </div>
      <div className="shimmer h-9 w-40 rounded mb-1" />
      <div className="shimmer h-5 w-20 rounded mb-4" />
      <div className="grid grid-cols-2 gap-3">
        <div className="shimmer h-12 rounded-xl" />
        <div className="shimmer h-12 rounded-xl" />
        <div className="shimmer h-12 rounded-xl" />
        <div className="shimmer h-12 rounded-xl" />
      </div>
    </Card>
  );
}

function StatTile({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      className="rounded-xl px-3 py-2.5"
      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)" }}
    >
      <div className="label-caps mb-1">{label}</div>
      <div
        className="text-[length:var(--t-sm)] font-semibold font-tabular"
        style={{ color: accent ? "inherit" : "rgb(226 232 240)" }}
      >
        {value}
      </div>
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
        <div className="flex items-center gap-2" style={{ color: "rgb(100 116 139)" }}>
          <Wallet size={16} />
          <span className="text-[length:var(--t-sm)]">{label} — no data yet</span>
        </div>
      </Card>
    );
  }

  const prefix = currency === "SGD" ? "S$" : "$";
  const uplPct = pct(snapshot.upl_pct);
  const Icon = uplPct.positive ? TrendingUp : TrendingDown;
  const posCount = positions?.length ?? 0;
  const totalMktVal = positions?.reduce((sum, p) => sum + Number(p.mkt_val || 0), 0) ?? 0;
  const positiveColor = "#34d399";
  const negativeColor = "#f87171";
  const pnlColor = uplPct.positive ? positiveColor : negativeColor;

  return (
    <Card>
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ background: pnlColor, boxShadow: `0 0 6px ${pnlColor}60` }}
          />
          <span className="text-[length:var(--t-sm)] font-semibold text-slate-300">{label}</span>
        </div>
        <time className="text-[length:var(--t-xs)] font-tabular" style={{ color: "rgb(100 116 139)" }}>
          {(snapshot.date ?? "").slice(0, 10)}
        </time>
      </div>

      {/* Big NLV number */}
      <div className="mb-1">
        <span className="text-[length:var(--t-hero)] font-bold tracking-[-0.03em] text-white font-tabular leading-none">
          {fmt(snapshot.net_liq, prefix)}
        </span>
      </div>

      {/* P&L badge */}
      <div className="flex items-center gap-2 mb-4">
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[length:var(--t-xs)] font-semibold font-tabular"
          style={{
            background: `${pnlColor}18`,
            color: pnlColor,
          }}
        >
          <Icon size={11} />
          {uplPct.text}
        </span>
        <span className="text-[length:var(--t-xs)] font-tabular" style={{ color: "rgb(100 116 139)" }}>
          UPL {fmt(snapshot.upl, prefix)}
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2">
        <StatTile label="Cash"         value={fmt(snapshot.cash, prefix)} />
        <StatTile label="Market Value" value={fmtCompact(totalMktVal, prefix)} />
        <StatTile label="Positions"    value={posCount > 0 ? `${posCount} holdings` : "—"} />
        <StatTile label="Day UPL"      value={fmt(snapshot.upl, prefix)} /></div>
    </Card>
  );
}
