/**
 * Concentration Alert — surfaces single-ticker over-exposure.
 *
 * Risk Parity audit catches asset-class drift, but a portfolio could
 * be 100% diversified across 8 asset classes and still be 50% NVDA in
 * the equity_us bucket. This card answers the orthogonal question:
 * "Is any one stock too large a piece of my pie?"
 *
 * Thresholds (per account):
 *   < 25%   safe       — not rendered
 *   25-30%  watch      — slate chip, informational
 *   30-40%  amber      — warning
 *   40%+    red        — critical (rebalance candidate)
 *
 * Returns null when no position crosses the lowest threshold (the
 * common case for a properly diversified book) so the card doesn't
 * eat home-page real estate when there's nothing to say.
 */
import type { PositionRow, SnapshotRow } from "../data";
import { Card } from "./Card";
import { AlertTriangle, ShieldAlert, Eye } from "lucide-react";
import { numeric } from "../data";

const WATCH_PCT  = 25;
const WARN_PCT   = 30;
const CRIT_PCT   = 40;

type Severity = "watch" | "warn" | "crit";

interface Hotspot {
  account: "caspar" | "sarah";
  ticker: string;
  pct: number;
  mktVal: number;
  severity: Severity;
}

function evaluateAccount(
  account: "caspar" | "sarah",
  positions: PositionRow[],
  snapshot: SnapshotRow | null,
): Hotspot[] {
  if (!positions.length) return [];
  // Prefer net_liq from snapshot (includes cash) for true portfolio share;
  // fall back to sum of position mkt_vals if snapshot is missing.
  const totalMkt = positions.reduce((s, r) => s + numeric(r.mkt_val), 0);
  const denom = snapshot ? numeric(snapshot.net_liq) || totalMkt : totalMkt;
  if (denom <= 0) return [];

  return positions
    .map((p) => {
      const mktVal = numeric(p.mkt_val);
      const pct = denom > 0 ? (mktVal / denom) * 100 : 0;
      return { p, mktVal, pct };
    })
    .filter(({ pct }) => pct >= WATCH_PCT)
    .map(({ p, mktVal, pct }) => ({
      account,
      ticker: (p.ticker || "").toUpperCase(),
      pct,
      mktVal,
      severity: (pct >= CRIT_PCT
        ? "crit"
        : pct >= WARN_PCT
        ? "warn"
        : "watch") as Severity,
    }))
    .sort((a, b) => b.pct - a.pct);
}

const SEVERITY_CONFIG: Record<Severity, { color: string; bg: string; border: string; label: string; Icon: typeof Eye }> = {
  watch: {
    color: "#94a3b8",
    bg: "rgba(148, 163, 184, 0.10)",
    border: "rgba(148, 163, 184, 0.20)",
    label: "Watch",
    Icon: Eye,
  },
  warn: {
    color: "#fcd34d",
    bg: "rgba(252, 211, 77, 0.10)",
    border: "rgba(252, 211, 77, 0.25)",
    label: "Warning",
    Icon: AlertTriangle,
  },
  crit: {
    color: "#fca5a5",
    bg: "rgba(252, 165, 165, 0.10)",
    border: "rgba(252, 165, 165, 0.25)",
    label: "Critical",
    Icon: ShieldAlert,
  },
};

export function ConcentrationCard({
  casparPositions,
  sarahPositions,
  casparSnapshot,
  sarahSnapshot,
}: {
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  casparSnapshot?: SnapshotRow | null;
  sarahSnapshot?: SnapshotRow | null;
}) {
  const hotspots: Hotspot[] = [
    ...evaluateAccount("caspar", casparPositions, casparSnapshot ?? null),
    ...evaluateAccount("sarah", sarahPositions, sarahSnapshot ?? null),
  ];

  // Render-only when at least one warn-or-worse exists. Plain "watch"
  // (25-30%) is normal for a concentrated book — surface only on
  // request via the link if needed; don't auto-fire on it.
  const hasMeaningful = hotspots.some((h) => h.severity !== "watch");
  if (!hasMeaningful) return null;

  // Group by account so the user can see "caspar has NVDA 42% AND TSLA 31%"
  // at a glance.
  const byAccount = new Map<string, Hotspot[]>();
  for (const h of hotspots) {
    const list = byAccount.get(h.account) ?? [];
    list.push(h);
    byAccount.set(h.account, list);
  }

  // Headline severity = highest severity across all rows.
  const top: Severity = hotspots.some((h) => h.severity === "crit")
    ? "crit"
    : hotspots.some((h) => h.severity === "warn")
    ? "warn"
    : "watch";
  const topCfg = SEVERITY_CONFIG[top];
  const TopIcon = topCfg.Icon;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TopIcon size={14} style={{ color: topCfg.color }} />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Concentration</h2>
        </div>
        <span
          className="text-[length:var(--t-2xs)] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider"
          style={{
            color: topCfg.color,
            background: topCfg.bg,
            border: `1px solid ${topCfg.border}`,
          }}
        >
          {topCfg.label}
        </span>
      </div>

      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
        Single tickers above {WARN_PCT}% of NLV. Asset-class diversification
        (Risk Parity audit) doesn't catch within-class concentration —
        e.g. NVDA 42% inside equity_us. {WARN_PCT}% = warning, {CRIT_PCT}% = critical.
      </p>

      <div className="space-y-2">
        {[...byAccount.entries()].map(([account, rows]) => (
          <div key={account}>
            <div className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500 mb-1">
              {account}
            </div>
            <div className="space-y-1">
              {rows.map((h) => (
                <HotspotRow key={`${h.account}-${h.ticker}`} hotspot={h} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function HotspotRow({ hotspot }: { hotspot: Hotspot }) {
  const cfg = SEVERITY_CONFIG[hotspot.severity];
  return (
    <div
      className="flex items-center justify-between gap-2 rounded-xl px-3 py-2"
      style={{
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
      }}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[length:var(--t-sm)] font-bold text-white">{hotspot.ticker}</span>
        <span
          className="text-[length:var(--t-2xs)] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider"
          style={{ color: cfg.color, background: "rgba(0,0,0,0.2)" }}
        >
          {cfg.label}
        </span>
      </div>
      <div className="flex items-center gap-3 text-[length:var(--t-xs)] tabular-nums">
        <span className="font-bold" style={{ color: cfg.color }}>
          {hotspot.pct.toFixed(1)}%
        </span>
        <span className="text-slate-500">
          ${hotspot.mktVal.toLocaleString("en-US", { maximumFractionDigits: 0 })}
        </span>
      </div>
    </div>
  );
}
