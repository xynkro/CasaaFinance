import type { ExposurePostureRow, SnapshotRow } from "../data";
import { numeric } from "../data";
import { Card } from "./Card";
import { AlertTriangle, Gauge } from "lucide-react";

/**
 * ExposureBudgetCard — Bloomberg-amber strip at the top of the Decisions tab.
 *
 * Reads the latest `exposure_posture` row + per-account snapshot, and
 * computes for each account:
 *   equity_value  = NLV - cash         (capital tied up in positions)
 *   equity_pct    = equity / NLV       (current % deployed)
 *   ceiling_value = ceiling_pct * NLV  (cap implied by exposure-coach)
 *   headroom      = ceiling_value - equity_value
 *
 * If `exposure_posture` is empty (cron hasn't run yet, or sheet GID
 * still placeholder), renders a single-line "awaiting first regime
 * cron" graceful fallback — never crashes.
 */

type Account = {
  label: "Caspar" | "Sarah";
  prefix: "$" | "S$";
  snapshot: SnapshotRow | null;
};

type BudgetStatus = "in_budget" | "near" | "over";

type AccountState = {
  label: string;
  prefix: string;
  equityPct: number;          // 0-100
  headroom: number;           // can be negative
  status: BudgetStatus;
} | null;

const RECOMMENDATION_LABEL: Record<string, string> = {
  NEW_ENTRY_ALLOWED: "Open",
  REDUCE_ONLY: "Reduce-only",
  CASH_PRIORITY: "Cash-priority",
};

/**
 * Format a money value compactly (k for ≥1k). Negative values get a
 * minus prefix BEFORE the currency symbol so it reads "−$2,562" not
 * "$-2,562".
 */
function fmtMoney(n: number, prefix: string): string {
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (abs >= 1000) {
    return `${sign}${prefix}${(abs / 1000).toFixed(1)}k`;
  }
  return `${sign}${prefix}${abs.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

function computeAccount(acc: Account, ceilingPct: number): AccountState {
  if (!acc.snapshot) return null;
  const nlv = numeric(acc.snapshot.net_liq);
  const cash = numeric(acc.snapshot.cash);
  if (!Number.isFinite(nlv) || nlv <= 0) return null;

  const equity = nlv - cash;
  const equityPct = (equity / nlv) * 100;
  const ceilingValue = (ceilingPct / 100) * nlv;
  const headroom = ceilingValue - equity;

  // Status:
  //   in_budget — within (ceiling - 5%)
  //   near       — within 5% of ceiling
  //   over       — past ceiling
  let status: BudgetStatus;
  if (equityPct > ceilingPct) {
    status = "over";
  } else if (equityPct >= ceilingPct - 5) {
    status = "near";
  } else {
    status = "in_budget";
  }

  return {
    label: acc.label,
    prefix: acc.prefix,
    equityPct,
    headroom,
    status,
  };
}

function statusColor(s: BudgetStatus | undefined): string {
  if (s === "over") return "#f87171";       // red
  if (s === "near") return "#fbbf24";       // amber (matches Bloomberg accent family)
  return "#34d399";                          // emerald
}

export function ExposureBudgetCard({
  posture,
  caspar,
  sarah,
}: {
  posture: ExposurePostureRow | null;
  caspar: SnapshotRow | null;
  sarah: SnapshotRow | null;
}) {
  // Graceful fallback — sheet empty or first cron hasn't run.
  if (!posture) {
    return (
      <Card>
        <div className="flex items-center gap-2.5 text-slate-500">
          <Gauge size={14} style={{ color: `rgb(var(--accent-rgb))` }} />
          <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider"
                style={{ color: `rgb(var(--accent-rgb))` }}>
            Exposure
          </span>
          <span className="text-[length:var(--t-xs)] text-slate-500">
            awaiting first regime cron
          </span>
        </div>
      </Card>
    );
  }

  const ceilingPct = numeric(posture.exposure_ceiling_pct);
  const recRaw = (posture.recommendation ?? "").toUpperCase();
  const recLabel = RECOMMENDATION_LABEL[recRaw] ?? recRaw ?? "—";
  const biasRaw = (posture.bias ?? "").toUpperCase();
  const partRaw = (posture.participation ?? "").toUpperCase();

  const casparState = computeAccount(
    { label: "Caspar", prefix: "$", snapshot: caspar },
    ceilingPct,
  );
  const sarahState = computeAccount(
    { label: "Sarah", prefix: "S$", snapshot: sarah },
    ceilingPct,
  );

  const bothOver =
    casparState?.status === "over" && sarahState?.status === "over";
  const anyOver =
    casparState?.status === "over" || sarahState?.status === "over";

  // Posture-derived "ceiling line" descriptor — not all backends will
  // have a regime drift label; we synthesise something compact.
  const ceilingDescriptor = (() => {
    const parts: string[] = [];
    if (biasRaw && biasRaw !== "NEUTRAL") parts.push(biasRaw);
    if (partRaw && partRaw !== "BROAD") parts.push(partRaw);
    return parts.join(" · ");
  })();

  return (
    <Card>
      <div className="flex flex-col gap-2.5">
        {/* Row 1 — EXPOSURE: per-account % deployed */}
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Gauge size={13} style={{ color: `rgb(var(--accent-rgb))` }} />
            <span
              className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider"
              style={{ color: `rgb(var(--accent-rgb))` }}
            >
              Exposure
            </span>
          </div>
          <div className="flex items-center gap-3 text-[length:var(--t-xs)] tabular-nums">
            {casparState && (
              <span style={{ color: statusColor(casparState.status) }}>
                <span className="text-slate-500 font-medium">{casparState.label}</span>{" "}
                <span className="font-semibold">{casparState.equityPct.toFixed(0)}%</span>
              </span>
            )}
            {casparState && sarahState && <span className="text-slate-700">·</span>}
            {sarahState && (
              <span style={{ color: statusColor(sarahState.status) }}>
                <span className="text-slate-500 font-medium">{sarahState.label}</span>{" "}
                <span className="font-semibold">{sarahState.equityPct.toFixed(0)}%</span>
              </span>
            )}
            {!casparState && !sarahState && (
              <span className="text-slate-500">no snapshot data</span>
            )}
          </div>
        </div>

        {/* Row 2 — CEILING: target % + posture descriptor */}
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
            Ceiling
          </span>
          <div className="flex items-center gap-2 text-[length:var(--t-xs)] tabular-nums">
            <span className="font-semibold" style={{ color: `rgb(var(--accent-rgb))` }}>
              {Number.isFinite(ceilingPct) ? `${ceilingPct.toFixed(0)}%` : "—"}
            </span>
            <span className="text-slate-500">
              ({ceilingDescriptor ? `${ceilingDescriptor}, ` : ""}
              <span className="font-medium text-slate-300">posture: {recLabel}</span>)
            </span>
          </div>
        </div>

        {/* Row 3 — HEADROOM: per-account currency, with warn icon if over */}
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
            Headroom
          </span>
          <div className="flex items-center gap-3 text-[length:var(--t-xs)] tabular-nums">
            {casparState && (
              <span style={{ color: statusColor(casparState.status) }}>
                {fmtMoney(casparState.headroom, casparState.prefix)}
              </span>
            )}
            {casparState && sarahState && <span className="text-slate-700">·</span>}
            {sarahState && (
              <span style={{ color: statusColor(sarahState.status) }}>
                {fmtMoney(sarahState.headroom, sarahState.prefix)}
              </span>
            )}
            {anyOver && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[length:var(--t-2xs)] font-medium"
                style={{
                  background: "rgba(248,113,113,0.12)",
                  color: "#f87171",
                  border: "1px solid rgba(248,113,113,0.22)",
                }}
              >
                <AlertTriangle size={10} />
                {bothOver ? "both over budget" : "over budget"}
              </span>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
