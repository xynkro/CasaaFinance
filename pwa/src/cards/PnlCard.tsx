import type { SnapshotRow, PositionRow, LivePriceRow } from "../data";
import { Card } from "./Card";
import { TrendingUp, TrendingDown, Wallet } from "lucide-react";
import { toAcctCcy } from "../lib/sgxFx";

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
  account,
  usdSgd,
  snapshot,
  positions,
  livePrices,
  livePricesUpdatedAt,
  loading,
}: {
  label: string;
  currency: "USD" | "SGD";
  /** "caspar" (USD base) or "sarah" (SGD base). Drives SGX-FX adjustment. */
  account: "caspar" | "sarah";
  /** Spot USD/SGD for FX-converting cross-currency holdings. */
  usdSgd: number;
  snapshot: SnapshotRow | null;
  positions?: PositionRow[];
  livePrices?: Map<string, LivePriceRow>;
  livePricesUpdatedAt?: string;
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
  const positiveColor = "#34d399";
  const negativeColor = "#f87171";

  // Live-price overlay (per-position) — when we have a TV-refreshed price
  // for a stock, recompute its mkt_val using current price. The grand-total
  // NLV stays authoritative from `snapshot.net_liq` (IBKR's number, which
  // includes options + FX conversion); we only use the live overlay to
  // SHIFT it by the delta between grab-time stock value and live stock
  // value. This avoids double-counting options or losing FX precision for
  // Sarah's mixed-currency book.
  const posCount = positions?.length ?? 0;
  // Both grab-time and live mkt_val are FX-normalised to the account's base
  // currency. SGX positions in Caspar's USD account convert SGD→USD; US
  // positions in Sarah's SGD account convert USD→SGD. Without this, the
  // delta between grab-time and live drifts by the FX-mismatch and the
  // displayed NLV diverges from IBKR's authoritative number.
  const grabStockMktVal = positions?.reduce((sum, p) => {
    const t = (p.ticker || "").toUpperCase();
    return sum + toAcctCcy(Number(p.mkt_val || 0), t, account, usdSgd);
  }, 0) ?? 0;
  const liveStockMktVal = positions?.reduce((sum, p) => {
    const t = (p.ticker || "").toUpperCase();
    const lp = livePrices?.get(t);
    const rawMv = lp && Number(lp.last) > 0
      ? Number(p.qty || 0) * Number(lp.last)
      : Number(p.mkt_val || 0);
    return sum + toAcctCcy(rawMv, t, account, usdSgd);
  }, 0) ?? 0;
  const stockDelta = liveStockMktVal - grabStockMktVal;

  // Authoritative NLV from IBKR snapshot, shifted by the live stock delta.
  // For Sarah (SGD account), the price delta is in USD (TV prices for US
  // stocks). Convert via the snapshot's implied FX rate (snapshot.net_liq /
  // total stocks-in-SGD ratio approximates well enough). Acceptably noisy —
  // the per-position cards show the truly accurate live mkt_val, while
  // this top-line is "snapshot ± live drift".
  const snapshotNlv = Number(snapshot.net_liq || 0);
  const liveNlv = snapshotNlv + stockDelta;
  // Prefer live UPL when we have it; otherwise the snapshot's UPL. Both
  // legs are FX-normalised so SGX UPL doesn't double-count for Caspar.
  const liveUpl = positions?.reduce((sum, p) => {
    const t = (p.ticker || "").toUpperCase();
    const lp = livePrices?.get(t);
    const rawUpl = lp && Number(lp.last) > 0
      ? Number(p.qty || 0) * (Number(lp.last) - Number(p.avg_cost || 0))
      : Number(p.upl || 0);
    return sum + toAcctCcy(rawUpl, t, account, usdSgd);
  }, 0) ?? 0;
  const uplPctVal = liveNlv > 0 ? liveUpl / liveNlv : Number(snapshot.upl_pct || 0);
  const uplPct = {
    text: `${uplPctVal >= 0 ? "+" : ""}${(uplPctVal * 100).toFixed(2)}%`,
    positive: uplPctVal >= 0,
  };
  const Icon = uplPct.positive ? TrendingUp : TrendingDown;
  const pnlColor = uplPct.positive ? positiveColor : negativeColor;
  // Market Value tile shows the live stock-only number for clarity. (Day
  // UPL stays on snapshot.upl which is IBKR-authoritative.)
  const liveMktVal = liveStockMktVal || grabStockMktVal;

  // Freshness chip prefers the live-price feed timestamp over the snapshot
  // timestamp (since live is much fresher — 5min vs 15min).
  const tsSource = livePricesUpdatedAt && livePrices && livePrices.size > 0
    ? livePricesUpdatedAt
    : snapshot.date;
  const ts = fmtRelative(tsSource);
  const ageMin = (() => {
    const d = parseSgtAudit(tsSource ?? "");
    return d ? Math.round((Date.now() - d.getTime()) / 60000) : -1;
  })();
  // Threshold tuned to live-price cadence (5min cron). >10min → amber.
  const stale = ageMin > 10;

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
          {/* Currency chip — keeps Caspar (USD) symmetric with Sarah (SGD)
              so neither account looks unlabelled at a glance. */}
          <span
            className="text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded font-tabular"
            style={{
              background: "rgba(148,163,184,0.10)",
              color: "rgb(148 163 184)",
              border: "1px solid rgba(148,163,184,0.18)",
            }}
            title={currency === "SGD" ? "Singapore Dollars" : "US Dollars"}
          >
            {currency}
          </span>
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

      {/* Big NLV number — live-overlay computed from cash + Σ(qty × live_price). */}
      <div className="mb-1">
        <span className="text-[length:var(--t-hero)] font-bold tracking-[-0.03em] text-white font-tabular leading-none">
          {fmt(liveNlv, prefix)}
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
          UPL {fmt(liveUpl, prefix)}
        </span>
      </div>

      {/* Stats grid — Market Value uses live overlay. The fourth tile is the
          IBKR snapshot's TOTAL UnrealizedPnL; it was labeled "Day UPL", which
          it has never been (same total-UPL concept as the live badge above,
          just from the slower snapshot). Label it honestly. */}
      <div className="grid grid-cols-2 gap-2">
        <StatTile label="Cash"            value={fmt(snapshot.cash, prefix)} />
        <StatTile label="Market Value"    value={fmtCompact(liveMktVal, prefix)} />
        <StatTile label="Positions"       value={posCount > 0 ? `${posCount} holdings` : "—"} />
        <StatTile label="UPL (snapshot)"  value={fmt(snapshot.upl, prefix)} /></div>
    </Card>
  );
}
