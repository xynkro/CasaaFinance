import type { WheelNextLegRow } from "../data";
import { Card } from "./Card";
import { Repeat, AlertCircle, ArrowRight, Clock } from "lucide-react";
import { useState } from "react";

const STATUS_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  HOLD: { bg: "bg-emerald-500/15 border-emerald-500/20", text: "text-emerald-400", label: "Let Ride" },
  EXPIRING_WORTHLESS: { bg: "bg-amber-500/15 border-amber-500/20", text: "text-amber-400", label: "Plan Next" },
  WIND_DOWN: { bg: "bg-amber-500/15 border-amber-500/20", text: "text-amber-400", label: "Wind Down" },
  LIKELY_ASSIGNED: { bg: "bg-red-500/15 border-red-500/20", text: "text-red-400", label: "Likely Assigned" },
  CATALYST_WARNING: { bg: "bg-orange-500/15 border-orange-500/20", text: "text-orange-400", label: "Catalyst ⚠" },
  EXPIRED: { bg: "bg-slate-500/15 border-slate-500/20", text: "text-slate-400", label: "Expired" },
};

function fmtPrice(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n) || n === 0) return "—";
  return `${prefix}${n.toFixed(2)}`;
}

function LegItem({ row }: { row: WheelNextLegRow }) {
  const [expanded, setExpanded] = useState(false);
  const status = row.current_status;
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.HOLD;
  const accountColor = row.account === "caspar" ? "text-blue-400" : "text-pink-400";
  const accountLabel = row.account === "caspar" ? "Caspar" : "Sarah";
  const dte = Number(row.current_dte);
  const confidence = Number(row.confidence);
  const nextDelta = Number(row.next_delta);
  const nextStrike = Number(row.next_strike);
  const nextPremium = Number(row.next_premium);
  const nextYield = Number(row.next_yield_pct);

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className={`w-full text-left glass rounded-xl p-3.5 space-y-2.5 active:bg-white/3 transition-colors border ${style.bg}`}
    >
      {/* Top: ticker + status */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker}</span>
          <span className="text-[length:var(--t-2xs)] font-semibold text-slate-500 shrink-0">
            ${Number(row.current_strike).toFixed(Number(row.current_strike) < 10 ? 1 : 0)}{row.current_right}
          </span>
          <span className={`text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider ${accountColor} shrink-0`}>
            {accountLabel}
          </span>
        </div>
        <div className={`shrink-0 px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${style.bg}`}>
          <span className={style.text}>{style.label}</span>
        </div>
      </div>

      {/* Current + DTE */}
      <div className="flex items-center justify-between text-[length:var(--t-2xs)]">
        <div className="flex items-center gap-2 text-slate-500">
          <Clock size={10} />
          <span className="tabular-nums">{dte}d DTE</span>
          {row.current_expiry && (
            <span>exp {row.current_expiry.length === 8
              ? `${row.current_expiry.slice(4, 6)}/${row.current_expiry.slice(6, 8)}`
              : row.current_expiry}</span>
          )}
        </div>
      </div>

      {/* Recommendation — the actionable line */}
      <div className="flex items-start gap-1.5 pt-1 border-t border-white/5">
        <ArrowRight size={11} className="text-indigo-400 mt-0.5 shrink-0" />
        <p className="text-[length:var(--t-xs)] text-slate-200 leading-relaxed">
          {row.recommendation || "No recommendation"}
        </p>
      </div>

      {/* Next leg metrics (if staged) */}
      {nextStrike > 0 && (
        <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500 pt-1.5 border-t border-white/5">
          <span>Next: <span className="text-slate-300 tabular-nums">${nextStrike.toFixed(2)}{row.next_right}</span></span>
          {nextDelta > 0 && (
            <span>Δ <span className="text-slate-300 tabular-nums">{nextDelta.toFixed(2)}</span></span>
          )}
          {nextPremium > 0 && (
            <span>Prem <span className="text-slate-300 tabular-nums">{fmtPrice(nextPremium)}</span></span>
          )}
          {nextYield > 0 && (
            <span>Yield <span className="text-emerald-400 tabular-nums font-semibold">{nextYield.toFixed(0)}%</span></span>
          )}
          {row.next_dte && Number(row.next_dte) > 0 && (
            <span>DTE <span className="text-slate-300 tabular-nums">{row.next_dte}d</span></span>
          )}
        </div>
      )}

      {/* Expanded: reasoning + confidence bar */}
      {expanded && (
        <div className="pt-2 border-t border-white/5 space-y-2">
          <div className="flex items-start gap-1.5">
            <AlertCircle size={10} className="text-slate-500 mt-0.5 shrink-0" />
            <p className="text-[length:var(--t-2xs)] text-slate-400 leading-relaxed">
              {row.reasoning || "No reasoning"}
            </p>
          </div>
          <div className="flex items-center gap-2 text-[length:var(--t-2xs)]">
            <span className="text-slate-500">Confidence:</span>
            <div className="flex-1 h-1 rounded-full bg-white/5 overflow-hidden">
              <div
                className={`h-full ${confidence >= 70 ? "bg-emerald-400" : confidence >= 40 ? "bg-amber-400" : "bg-red-400"} transition-all`}
                style={{ width: `${Math.max(0, Math.min(100, confidence))}%` }}
              />
            </div>
            <span className="tabular-nums text-slate-300 font-semibold">{confidence}</span>
          </div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">
            Action: <span className="text-indigo-400 font-medium">{row.next_action}</span>
            {row.next_strategy && <> · Strategy: <span className="text-indigo-400 font-medium">{row.next_strategy}</span></>}
          </div>
        </div>
      )}
    </button>
  );
}

export function WheelContinuationCard({ rows }: { rows: WheelNextLegRow[] }) {
  if (!rows.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Repeat size={16} />
          <span className="text-[length:var(--t-sm)]">No open options to continue</span>
        </div>
      </Card>
    );
  }

  // Sort by urgency: CATALYST_WARNING + LIKELY_ASSIGNED first, then EXPIRING_WORTHLESS, then HOLD
  const priority: Record<string, number> = {
    LIKELY_ASSIGNED: 0,
    CATALYST_WARNING: 1,
    EXPIRING_WORTHLESS: 2,
    WIND_DOWN: 3,
    HOLD: 4,
    EXPIRED: 5,
  };
  const sorted = [...rows].sort(
    (a, b) => (priority[a.current_status] ?? 6) - (priority[b.current_status] ?? 6)
  );

  const urgent = rows.filter(
    (r) => r.current_status === "LIKELY_ASSIGNED" ||
           r.current_status === "CATALYST_WARNING" ||
           r.current_status === "EXPIRING_WORTHLESS"
  ).length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Repeat size={14} className="text-indigo-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Wheel Continuation</h2>
        </div>
        <div className="flex items-center gap-2">
          {urgent > 0 && (
            <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/20">
              {urgent} NEED ACTION
            </span>
          )}
          <span className="text-[length:var(--t-2xs)] text-slate-600">{rows.length} positions</span>
        </div>
      </div>

      <div className="space-y-2">
        {sorted.map((r, i) => (
          <LegItem key={`${r.ticker}-${r.current_strike}-${r.current_right}-${i}`} row={r} />
        ))}
      </div>
    </Card>
  );
}
