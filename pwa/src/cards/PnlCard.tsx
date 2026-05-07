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

/**
 * Parse a sheet audit timestamp like "2026-05-07T233619" or
 * "2026-05-07T23:36:19" → Date. Sheet writes use the SGT-anchored
 * suffix `_ts_suffix()` which lacks colons in the time part.
 */
function parseSgtAudit(s: string): Date | null {
  if (!s) return null;
  // YYYY-MM-DDTHHMMSS → YYYY-MM-DDTHH:MM:SS+08:00 (SGT)
  const m = s.match(/^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})$/);
  if (m) {
    const iso = `${m[1]}T${m[2]}:${m[3]}:${m[4]}+08:00`;
    const d = new Date(iso);
    return isNaN(d.getTime()) ? null : d;
  }
  // Fallback: rely on Date parser for already-colon-separated ISO.
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Render "X min ago" / "Just now" / "Yesterday" with the actual
 * timestamp on hover. Powers the Portfolio freshness chip.
 */
function fmtRelative(s: string | undefined): { short: string; full: string } {
  if (!s) return { short: "—", full: "" };
  const d = parseSgtAudit(s);
  if (!d) return { short: s.slice(0, 10), full: s };
  const ageMs = Date.now() - d.getTime();
  const min = Math.round(ageMs / 60000);
  const full = d.toLocaleString("en-SG", {
    timeZone: "Asia/Singapore",
    hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short",
  });
  let short: string;
  if (min < 0) short = "Just now";
  else if (min < 1) short = "Just now";
  else if (min < 60) short = `${min} min ago`;
  else if (min < 24 * 60) short = `${Math.floor(min / 60)}h ago`;
  else short = `${Math.floor(min / (24 * 60))}d ago`;
  return { short, full };
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

  const ts = fmtRelative(snapshot.date);
  // Highlight stale data. >30 min during US-market window suggests yahoo-grab
  // missed a beat; >2h during off-hours is normal. Coloring uses the same
  // green/red palette as the rest of the card so it doesn't look bolted on.
  const ageMin = (() => {
    const d = parseSgtAudit(snapshot.date ?? "");
    return d ? Math.round((Date.now() - d.getTime()) / 60000) : -1;
  })();
  const stale = ageMin > 30; // 15min cron + slack

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
        {/* Freshness chip — replaces the static "YYYY-MM-DD" tag with a
            relative "X min ago" so the user can see at a glance how live
            the prices are. Hover/long-press shows the full timestamp. */}
        <time
          className="text-[length:var(--t-xs)] font-tabular"
          title={ts.full}
          style={{ color: stale ? "#fbbf24" : "rgb(100 116 139)" }}
        >
          {ts.short}
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
