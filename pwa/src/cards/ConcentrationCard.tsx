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
 * ALWAYS renders the top holding per account (a compact one-liner) so
 * drift is visible BEFORE it crosses the warn line — e.g. SCHD at 27%
 * surfaces before it becomes a 30% problem (UI-audit #8). Escalates to
 * the full illustrated hotspot view once a name crosses WARN.
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

interface TopHolding { account: "caspar" | "sarah"; ticker: string; pct: number; }

/** The single largest holding in an account, as a % of NLV — computed
 *  regardless of threshold so drift is visible BEFORE it crosses the warn
 *  line (UI-audit #8: see SCHD at 27% before it becomes a 30% problem). */
function topHolding(
  account: "caspar" | "sarah",
  positions: PositionRow[],
  snapshot: SnapshotRow | null,
): TopHolding | null {
  if (!positions.length) return null;
  const totalMkt = positions.reduce((s, r) => s + numeric(r.mkt_val), 0);
  const denom = snapshot ? numeric(snapshot.net_liq) || totalMkt : totalMkt;
  if (denom <= 0) return null;
  let best: TopHolding | null = null;
  for (const p of positions) {
    const pct = (numeric(p.mkt_val) / denom) * 100;
    if (!best || pct > best.pct) {
      best = { account, ticker: (p.ticker || "").toUpperCase(), pct };
    }
  }
  return best;
}

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

  const hasMeaningful = hotspots.some((h) => h.severity !== "watch");

  // CALM state: nothing has crossed WARN, but ALWAYS surface the top holding
  // per account (UI-audit #8 — drift visibility). Compact one-liner, no
  // illustration, minimal footprint.
  if (!hasMeaningful) {
    const tops = [
      topHolding("caspar", casparPositions, casparSnapshot ?? null),
      topHolding("sarah", sarahPositions, sarahSnapshot ?? null),
    ].filter((t): t is TopHolding => t !== null);
    if (!tops.length) return null;
    return (
      <Card>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Eye size={14} className="text-slate-500" />
            <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Concentration</h2>
          </div>
          <span className="text-[length:var(--t-2xs)] text-slate-600">top holding / account</span>
        </div>
        <div className="space-y-1">
          {tops.map((t) => {
            const color = t.pct >= WARN_PCT ? "#fcd34d" : t.pct >= WATCH_PCT ? "#cbd5e1" : "#64748b";
            return (
              <div key={t.account} className="flex items-center justify-between">
                <span className="text-[length:var(--t-2xs)] uppercase tracking-wide text-slate-500">{t.account}</span>
                <span className="text-[length:var(--t-xs)] tabular-nums">
                  <span className="text-slate-300 font-semibold">{t.ticker}</span>{" "}
                  <span className="font-bold" style={{ color }}>{t.pct.toFixed(1)}%</span>
                </span>
              </div>
            );
          })}
        </div>
      </Card>
    );
  }

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

      {/* Concentration visual — one bar dominating the others. Card only
          renders when a position has crossed WARN_PCT, so the imbalance
          metaphor only shows in the moment of truth. */}
      <div className="mb-3 flex items-start gap-3">
        <img
          src={`${import.meta.env.BASE_URL}concentration.jpg`}
          alt=""
          aria-hidden="true"
          className="w-14 h-14 rounded-lg shrink-0"
        />
        <p className="text-[length:var(--t-2xs)] text-slate-500 leading-relaxed">
          Single tickers above {WARN_PCT}% of NLV. Asset-class diversification
          (Risk Parity audit) doesn't catch within-class concentration —
          e.g. NVDA 42% inside equity_us. {WARN_PCT}% = warning, {CRIT_PCT}% = critical.
        </p>
      </div>

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
