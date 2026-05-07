import type { RiskParityAuditRow } from "../data";
import { numeric } from "../data";
import { Card } from "./Card";
import { Scale, ArrowRightCircle } from "lucide-react";

/**
 * RiskAllocationCard — Risk Parity LITE diversification panel.
 *
 * Renders the latest `risk_parity_audit` snapshot as TWO mini sections
 * (Caspar then Sarah). Each section shows 8 horizontal bars — one per
 * canonical asset class — with the bar fill = `capital_pct` colored by
 * `rebalance_action` (red OVERWEIGHT / amber UNDERWEIGHT / slate ON_TARGET),
 * a target tick mark at `target_pct`, and a signed delta-pp number to
 * the right. Below the bars: a one-line "top gap" headline pulling the
 * largest UNDERWEIGHT row's class name and `rebalance_amount_usd`.
 *
 * Empty state (audit not yet written — sheet GID still placeholder, or
 * the daily 22:45 UTC cron hasn't run today) renders the graceful
 * "back tomorrow morning" fallback.
 */

// Canonical 8-class taxonomy — order is the same as the audit script writes
// against, kept stable so the bars always render in a predictable sequence
// regardless of cron row order.
const CLASS_ORDER = [
  "equity_us",
  "equity_us_dividend",
  "equity_intl",
  "bond_long",
  "bond_intermediate",
  "gold",
  "commodities_broad",
  "vol_long",
];

const CLASS_LABELS: Record<string, string> = {
  equity_us:           "equity_us",
  equity_us_dividend:  "equity_us_div",
  equity_intl:         "equity_intl",
  bond_long:           "bond_long",
  bond_intermediate:   "bond_int",
  gold:                "gold",
  commodities_broad:   "commodities",
  vol_long:            "vol_long",
};

/**
 * Preferred starter ticker per asset class. Mirrors `prompts/watchlist.yaml`
 * `asset_classes:` map but exposes ONE canonical "first add" candidate per
 * class for the cross-account rebalance hint list. The brain still surfaces
 * the full universe; this is only for the PWA suggestion line.
 *
 * Liquid first → TLT (not EDV/ZROZ); GLD (not GLDM/GDX); IEF (not BIV/AGG).
 * Skip equity_us/equity_us_dividend/equity_intl — those are situation-
 * dependent (the brain picks SCHD vs JPM vs XLV from regime context).
 */
const STARTER_TICKER: Record<string, string> = {
  bond_long:         "TLT",
  bond_intermediate: "IEF",
  gold:              "GLD",
  commodities_broad: "DBC",
  vol_long:          "VIXM",
  equity_intl:       "VEA",   // hint only — Sarah's intl is SGX-traded
  equity_us_dividend:"SCHD",
};

type AccountKey = "caspar" | "sarah";

function fmtMoney(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "$0";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function fmtDelta(deltaPct: number): string {
  const abs = Math.abs(deltaPct);
  if (abs < 0.05) return "0pp";
  const sign = deltaPct > 0 ? "+" : "-";
  return `${sign}${abs.toFixed(abs >= 10 ? 0 : 1)}pp`;
}

/** Build a deterministic 8-row list for one account, ordered by CLASS_ORDER. */
function rowsForAccount(rows: RiskParityAuditRow[], account: AccountKey): RiskParityAuditRow[] {
  const byClass = new Map<string, RiskParityAuditRow>();
  for (const r of rows) {
    if ((r.account ?? "").toLowerCase() === account) {
      byClass.set(r.asset_class, r);
    }
  }
  const out: RiskParityAuditRow[] = [];
  for (const k of CLASS_ORDER) {
    const r = byClass.get(k);
    if (r) out.push(r);
  }
  // Forward-compat: append any extra classes the audit may add later.
  for (const r of rows) {
    if (
      (r.account ?? "").toLowerCase() === account &&
      !CLASS_ORDER.includes(r.asset_class)
    ) {
      out.push(r);
    }
  }
  return out;
}

/** Pick the most-underweight row (largest negative delta_pct) for the headline. */
function topGapFor(rows: RiskParityAuditRow[]): RiskParityAuditRow | null {
  let best: RiskParityAuditRow | null = null;
  let bestDelta = 0;
  for (const r of rows) {
    if ((r.rebalance_action ?? "").toUpperCase() !== "UNDERWEIGHT") continue;
    const d = numeric(r.delta_pct);
    if (d < bestDelta) {
      bestDelta = d;
      best = r;
    }
  }
  return best;
}

/**
 * Cross-account top-3 underweight rebalance suggestions.
 *
 * Sort all UNDERWEIGHT rows from both accounts by delta_pct ASC (most
 * negative first), take top 3. Each entry pulls a starter ticker from
 * `STARTER_TICKER` (or omits if no preferred candidate). Rendered as a
 * small list under the two account sections.
 */
function topRebalanceSuggestions(rows: RiskParityAuditRow[]): RiskParityAuditRow[] {
  const ranked = rows
    .filter((r) => (r.rebalance_action ?? "").toUpperCase() === "UNDERWEIGHT")
    .filter((r) => numeric(r.delta_pct) < -5)
    .sort((a, b) => numeric(a.delta_pct) - numeric(b.delta_pct));
  return ranked.slice(0, 3);
}

/**
 * Single asset-class horizontal bar row.
 *
 * Layout (left → right):
 *   [class label, 80px][stacked bar with target tick, flex-1][delta, ~52px]
 *
 * The bar track is 8px tall, dark slate; the fill is colored by action
 * and clamped to [0, 100]; the target tick is a 2px-wide white-ish marker
 * at `target_pct` of the track width.
 */
function ClassBar({ row }: { row: RiskParityAuditRow }) {
  const capPct = Math.max(0, Math.min(100, numeric(row.capital_pct)));
  const targetPct = Math.max(0, Math.min(100, numeric(row.target_pct)));
  const delta = numeric(row.delta_pct);
  const action = (row.rebalance_action ?? "").toUpperCase();

  // Color tokens (per spec) — overweight red, underweight amber, on-target slate.
  let fillBg = "bg-slate-500/40";
  let deltaCls = "text-slate-400";
  if (action === "OVERWEIGHT") {
    fillBg = "bg-red-500/70";
    deltaCls = "text-red-400";
  } else if (action === "UNDERWEIGHT") {
    fillBg = "bg-amber-500/70";
    deltaCls = "text-amber-400";
  }

  const label = CLASS_LABELS[row.asset_class] ?? row.asset_class;

  return (
    <div className="flex items-center gap-2">
      <div
        className="text-[length:var(--t-2xs)] text-slate-300 tabular-nums truncate shrink-0"
        style={{ width: 78 }}
        title={row.asset_class}
      >
        {label}
      </div>
      <div className="flex-1 min-w-0 flex items-center gap-1.5">
        {/* Track */}
        <div className="flex-1 relative h-2 rounded-full bg-slate-800/70 overflow-visible">
          {/* Capital fill */}
          <div
            className={`absolute inset-y-0 left-0 rounded-full ${fillBg}`}
            style={{ width: `${capPct}%` }}
          />
          {/* Target tick — 2px wide, slightly taller than track for visibility */}
          <div
            className="absolute bg-slate-100"
            style={{
              left: `calc(${targetPct}% - 1px)`,
              top: -2,
              bottom: -2,
              width: 2,
              borderRadius: 1,
              opacity: 0.85,
            }}
            title={`Target ${targetPct.toFixed(0)}%`}
          />
        </div>
        {/* Capital pct numeric (small, tight) */}
        <span className="text-[length:var(--t-2xs)] text-slate-400 tabular-nums shrink-0" style={{ minWidth: 28, textAlign: "right" }}>
          {capPct.toFixed(0)}%
        </span>
      </div>
      <span
        className={`text-[length:var(--t-2xs)] tabular-nums font-semibold shrink-0 ${deltaCls}`}
        style={{ minWidth: 44, textAlign: "right" }}
      >
        {fmtDelta(delta)}
      </span>
    </div>
  );
}

function AccountSection({
  account,
  rows,
}: {
  account: AccountKey;
  rows: RiskParityAuditRow[];
}) {
  const accountLabel = account === "caspar" ? "Caspar" : "Sarah";
  const accountColor = account === "caspar" ? "text-blue-300" : "text-pink-300";
  const gap = topGapFor(rows);

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <h3 className={`text-[length:var(--t-xs)] font-semibold ${accountColor}`}>
          {accountLabel} — Risk Allocation
        </h3>
      </div>
      <div className="space-y-1.5 mb-2.5">
        {rows.map((r) => (
          <ClassBar key={r.asset_class} row={r} />
        ))}
      </div>
      {gap ? (
        <p className="text-[length:var(--t-2xs)] text-slate-400 leading-relaxed">
          <span className="text-slate-500">Top gap:</span>{" "}
          <span className="text-amber-300 font-medium">
            {gap.asset_class} {fmtDelta(numeric(gap.delta_pct))}
          </span>
          <span className="text-slate-500"> ({fmtMoney(numeric(gap.rebalance_amount_usd))} starter to hit target)</span>
        </p>
      ) : (
        <p className="text-[length:var(--t-2xs)] text-slate-500 leading-relaxed">
          No underweight gap &gt; 5pp — diversification ON_TARGET.
        </p>
      )}
    </div>
  );
}

export function RiskAllocationCard({
  riskParityAudit,
}: {
  riskParityAudit: RiskParityAuditRow[];
}) {
  // Empty state — Agent 1's cron hasn't run yet, or the sheet GID is still
  // the placeholder zero, or today's run isn't in yet.
  if (!riskParityAudit || riskParityAudit.length === 0) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-2">
          <Scale size={14} style={{ color: "var(--accent)" }} />
          <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">
            Risk Allocation
          </h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 leading-relaxed">
          Risk allocation snapshot pending — runs daily 22:45 UTC.
        </p>
      </Card>
    );
  }

  const casparRows = rowsForAccount(riskParityAudit, "caspar");
  const sarahRows = rowsForAccount(riskParityAudit, "sarah");
  const suggestions = topRebalanceSuggestions(riskParityAudit);

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Scale size={14} style={{ color: "var(--accent)" }} />
          <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">
            Risk Allocation
          </h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-500">
          OW · UW · OT
        </span>
      </div>

      <div className="space-y-4">
        {casparRows.length > 0 && (
          <AccountSection account="caspar" rows={casparRows} />
        )}
        {sarahRows.length > 0 && (
          <AccountSection account="sarah" rows={sarahRows} />
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="mt-4 pt-3 border-t border-slate-700/50">
          <div className="flex items-center gap-1.5 mb-2">
            <ArrowRightCircle size={12} className="text-slate-400" />
            <h3 className="text-[length:var(--t-2xs)] font-semibold text-slate-300 uppercase tracking-wide">
              Top rebalance suggestions
            </h3>
          </div>
          <ul className="space-y-1">
            {suggestions.map((r) => {
              const account = (r.account ?? "").toLowerCase();
              const accountLabel = account === "caspar" ? "Caspar" : account === "sarah" ? "Sarah" : r.account;
              const accountColor = account === "caspar" ? "text-blue-300" : "text-pink-300";
              const ticker = STARTER_TICKER[r.asset_class];
              const amount = numeric(r.rebalance_amount_usd);
              const delta = numeric(r.delta_pct);
              return (
                <li
                  key={`${r.account}-${r.asset_class}`}
                  className="flex items-baseline gap-2 text-[length:var(--t-2xs)] leading-relaxed"
                >
                  <span className={`${accountColor} font-medium shrink-0`}>{accountLabel}</span>
                  <span className="text-slate-300 truncate">
                    {r.asset_class}{" "}
                    <span className="text-amber-400 tabular-nums">{fmtDelta(delta)}</span>
                  </span>
                  <span className="text-slate-500 tabular-nums shrink-0 ml-auto">
                    {fmtMoney(amount)}
                    {ticker ? <span className="text-slate-300"> → {ticker}</span> : null}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-[length:var(--t-2xs)] text-slate-500 leading-relaxed">
            Use 25-50% of suggested $ as a starter; brain proposes specific entry from watchlist.
          </p>
        </div>
      )}
    </Card>
  );
}
