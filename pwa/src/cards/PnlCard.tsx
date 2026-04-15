import type { SnapshotRow } from "../data";
import { Card } from "./Card";
import { TrendingUp, TrendingDown } from "lucide-react";

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

export function PnlCard({
  label,
  currency,
  snapshot,
}: {
  label: string;
  currency: "USD" | "SGD";
  snapshot: SnapshotRow | null;
}) {
  if (!snapshot) {
    return (
      <Card>
        <p className="text-sm text-slate-500">{label} P&L — no data yet</p>
      </Card>
    );
  }

  const prefix = currency === "SGD" ? "S$" : "$";
  const uplPct = pct(snapshot.upl_pct);
  const Icon = uplPct.positive ? TrendingUp : TrendingDown;

  return (
    <Card>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-medium text-slate-400">{label}</h2>
        <time className="text-xs text-slate-500">{snapshot.date}</time>
      </div>

      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-bold text-slate-100">
          {fmt(snapshot.net_liq, prefix)}
        </span>
        <span
          className={`flex items-center gap-1 text-sm font-medium ${
            uplPct.positive ? "text-emerald-400" : "text-red-400"
          }`}
        >
          <Icon size={14} />
          {uplPct.text}
        </span>
      </div>

      <div className="mt-2 flex gap-4 text-xs text-slate-400">
        <span>Cash {fmt(snapshot.cash, prefix)}</span>
        <span>UPL {fmt(snapshot.upl, prefix)}</span>
      </div>
    </Card>
  );
}
