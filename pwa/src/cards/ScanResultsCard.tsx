import { useState } from "react";
import type { ScanResultRow } from "../data";
import { Card } from "./Card";
import { fmtExpiry } from "../lib/dates";
import { TrendingUp, ChevronDown, ChevronUp } from "lucide-react";

/** Strategy-specific contract label: "$190P" for puts, "$200C" for calls, "$190P/$185P" for spreads. */
function contractLabel(row: ScanResultRow): string {
  const strike = Number(row.strike) || 0;
  const right = (row.right || "").toUpperCase();
  const strategy = (row.strategy || "").toUpperCase();

  // Multi-leg strategies — parse the notes field for leg details
  if (strategy === "PCS" || strategy === "CCS" || strategy === "IC" || strategy === "PMCC") {
    const notes = row.notes || "";
    if (notes) {
      // Notes contain leg descriptions like "sell 190P / buy 185P"
      // Try to extract a compact representation
      const legs = notes.match(/\d+\.?\d*[PC]/gi);
      if (legs && legs.length >= 2) {
        return legs.slice(0, 2).map((l) => `$${l}`).join("/");
      }
    }
    // Fallback: show main strike + right
    if (right) return `$${strike.toFixed(0)}${right}`;
    return `$${strike.toFixed(0)}`;
  }

  // Single-leg: CSP → "$190P", CC → "$200C", LONG_CALL → "$200C"
  const suffix = right || (strategy === "CSP" ? "P" : strategy === "CC" ? "C" : strategy === "LONG_CALL" ? "C" : "");
  return `$${strike.toFixed(0)}${suffix}`;
}

function scoreColor(score: number) {
  if (score >= 70) return "text-emerald-400 bg-emerald-500/15 border-emerald-500/30";
  if (score >= 50) return "text-amber-400 bg-amber-500/15 border-amber-500/30";
  return "text-slate-400 bg-slate-500/15 border-slate-500/30";
}

/** Strategy-specific accent color for the header icon. */
function strategyAccent(strategy: string): string {
  switch (strategy) {
    case "CSP": return "text-amber-400";
    case "CC": return "text-blue-400";
    case "PCS": return "text-violet-400";
    case "CCS": return "text-rose-400";
    case "IC": return "text-cyan-400";
    case "PMCC": return "text-emerald-400";
    case "LONG_CALL": return "text-lime-400";
    default: return "text-slate-400";
  }
}

const STRATEGY_LABELS: Record<string, string> = {
  CSP: "Cash-Secured Put",
  CC: "Covered Call",
  PCS: "Put Credit Spread",
  CCS: "Call Credit Spread",
  IC: "Iron Condor",
  PMCC: "Poor Man's CC",
  LONG_CALL: "Long Call",
};

function ScanRow({ row }: { row: ScanResultRow }) {
  const [expanded, setExpanded] = useState(false);
  const score = Number(row.composite_score) || 0;
  const premium = Number(row.premium) || 0;
  const yld = Number(row.annual_yield_pct) || 0;
  const dte = Number(row.dte) || 0;
  const ivr = Number(row.iv_rank) || 0;
  const last = Number(row.underlying_last) || 0;
  const delta = Number(row.delta) || 0;
  const iv = Number(row.iv) || 0;
  const spread = Number(row.spread_pct) || 0;
  const brk = Number(row.breakeven) || 0;
  const cash = Number(row.cash_required) || 0;
  const techScore = Number(row.technical_score) || 0;

  return (
    <div
      className="border-b border-white/3 last:border-0 py-2.5 cursor-pointer"
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-center gap-2">
        <span className="font-bold text-[length:var(--t-sm)]">{row.ticker}</span>
        <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${scoreColor(score)}`}>
          {score.toFixed(0)}
        </span>
        <span className="text-[length:var(--t-xs)] text-slate-400 ml-auto">
          {contractLabel(row)} · {fmtExpiry(row.expiry)}
        </span>
        <span className="text-[length:var(--t-xs)] text-emerald-400 font-mono">${premium.toFixed(2)}</span>
        {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </div>
      <div className="flex gap-3 mt-0.5 text-[length:var(--t-2xs)] text-slate-500">
        <span>{dte}d</span>
        <span>{yld.toFixed(0)}% ann</span>
        <span>IVR {ivr.toFixed(0)}</span>
        <span>{delta.toFixed(2)}{"Δ"}</span>
      </div>

      {expanded && (
        <div className="mt-2 space-y-1 text-[length:var(--t-2xs)] text-slate-400">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <span>Underlying: <span className="text-white font-mono">${last.toFixed(2)}</span></span>
            <span>IV: <span className="text-white font-mono">{(iv * 100).toFixed(0)}%</span></span>
            <span>Breakeven: <span className="text-white font-mono">${brk.toFixed(2)}</span></span>
            <span>Spread: <span className="text-white font-mono">{spread.toFixed(1)}%</span></span>
            <span>Cash req: <span className="text-white font-mono">${cash.toFixed(0)}</span></span>
            <span>Tech score: <span className="text-white font-mono">{techScore.toFixed(1)}</span></span>
          </div>
          {row.notes && (
            <div className="text-slate-500 mt-1">
              <span className="font-semibold">Legs:</span> {row.notes}
            </div>
          )}
          {row.catalyst_flag === "TRUE" && (
            <div className="text-amber-400 mt-1">Catalyst flag</div>
          )}
        </div>
      )}
    </div>
  );
}

export function ScanResultsCard({
  strategy,
  rows,
}: {
  strategy: string;
  rows: ScanResultRow[];
}) {
  if (!rows.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp size={14} className={strategyAccent(strategy)} />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">
            {STRATEGY_LABELS[strategy] || strategy}
          </h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          No {strategy} candidates found today.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className={strategyAccent(strategy)} />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">
            {STRATEGY_LABELS[strategy] || strategy}
          </h2>
        </div>
        <span className={`${strategyAccent(strategy)} text-[length:var(--t-2xs)] tabular-nums`}>
          {rows.length} picks
        </span>
      </div>
      <div>
        {rows.map((r, i) => <ScanRow key={`${r.ticker}-${r.strike}-${i}`} row={r} />)}
      </div>
    </Card>
  );
}
