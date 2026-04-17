import type { OptionRecommendationRow } from "../data";
import { Card } from "./Card";
import { Lightbulb, ChevronRight, TrendingUp } from "lucide-react";
import { useState } from "react";

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: string | number): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

const STRATEGY_LABEL: Record<string, string> = {
  CSP: "Cash-Secured Put",
  CC: "Covered Call",
  LONG_CALL: "Long Call",
  LONG_PUT: "Long Put",
  PMCC: "Poor Man's Covered Call",
};

const STATUS_STYLE: Record<string, string> = {
  proposed: "bg-indigo-500/15 text-indigo-400 border-indigo-500/20",
  executed: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
  skipped: "bg-slate-500/15 text-slate-400 border-slate-500/20",
  expired: "bg-amber-500/15 text-amber-400 border-amber-500/20",
};

function ThesisConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color = pct >= 70 ? "bg-emerald-400" : pct >= 50 ? "bg-indigo-400" : "bg-amber-400";
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <div className="w-10 h-1 rounded-full bg-white/5 overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-semibold tabular-nums text-slate-300">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

function RecItem({ rec }: { rec: OptionRecommendationRow }) {
  const [expanded, setExpanded] = useState(false);
  const strategy = STRATEGY_LABEL[rec.strategy] ?? rec.strategy;
  const status = rec.status?.toLowerCase() || "proposed";
  const statusStyle = STATUS_STYLE[status] ?? STATUS_STYLE.proposed;
  const accountLabel = rec.account === "caspar" ? "Caspar" : "Sarah";
  const accountColor = rec.account === "caspar" ? "text-blue-400" : "text-pink-400";
  const strike = Number(rec.strike);
  const yld = Number(rec.annual_yield_pct);

  // Format expiry — could be "May24" or "20260524"
  let expiryDisplay = rec.expiry;
  if (rec.expiry.length === 8 && /^\d+$/.test(rec.expiry)) {
    expiryDisplay = `${rec.expiry.slice(4, 6)}/${rec.expiry.slice(6, 8)}`;
  }

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className="w-full text-left glass rounded-xl p-3.5 space-y-2.5 active:bg-white/3 transition-colors border border-white/5"
    >
      {/* Header: action + ticker + strike + status */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <TrendingUp size={12} className="text-emerald-400 shrink-0" />
          <span className="text-sm font-bold text-white">{rec.ticker}</span>
          <span className="text-[10px] font-semibold text-slate-500 shrink-0">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{rec.right}
          </span>
          <span className="text-[9px] text-slate-600">exp {expiryDisplay}</span>
        </div>
        <div className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-bold border ${statusStyle}`}>
          {status.toUpperCase()}
        </div>
      </div>

      {/* Strategy + account */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium text-indigo-400">{strategy}</span>
          <span className={`text-[10px] font-semibold uppercase tracking-wider ${accountColor}`}>
            {accountLabel}
          </span>
        </div>
        <ChevronRight size={12} className="text-slate-600" />
      </div>

      {/* Key metrics */}
      <div className="flex items-center flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
        <span>Premium: <span className="text-slate-300 tabular-nums">{fmt(rec.premium_per_share)}</span></span>
        <span>Yield: <span className="text-emerald-400 tabular-nums font-semibold">{fmtPct(yld)}</span></span>
        <span>Cash: <span className="text-slate-300 tabular-nums">{fmt(rec.cash_required)}</span></span>
        <span>Δ: <span className="text-slate-300 tabular-nums">{Number(rec.delta).toFixed(2)}</span></span>
      </div>

      {/* Breakeven + IV + confidence */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-[10px] text-slate-500">
          <span>BE: <span className="text-slate-300 tabular-nums">{fmt(rec.breakeven)}</span></span>
          <span>IVR: <span className="text-slate-300 tabular-nums">{Number(rec.iv_rank).toFixed(0)}</span></span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-500">Conf</span>
          <ThesisConfidenceBar value={Number(rec.thesis_confidence) || 0} />
        </div>
      </div>

      {expanded && rec.thesis && (
        <div className="pt-2.5 border-t border-white/5">
          <p className="text-[11px] text-slate-400 leading-relaxed">{rec.thesis}</p>
          {rec.source && (
            <p className="text-[10px] text-slate-600 mt-1.5">Source: {rec.source}</p>
          )}
        </div>
      )}
    </button>
  );
}

export function RecommendationCard({ recommendations }: { recommendations: OptionRecommendationRow[] }) {
  if (!recommendations.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Lightbulb size={16} />
          <span className="text-sm">No strategy recommendations yet</span>
        </div>
        <p className="text-[10px] text-slate-600 mt-1.5 pl-6">
          Drop an options scan into Weekly Strategy Review to auto-populate
        </p>
      </Card>
    );
  }

  // Sort: proposed first, then by thesis_confidence desc, then by yield desc
  const statusOrder: Record<string, number> = { proposed: 0, executed: 1, expired: 2, skipped: 3 };
  const sorted = [...recommendations].sort((a, b) => {
    const sa = statusOrder[a.status?.toLowerCase()] ?? 4;
    const sb = statusOrder[b.status?.toLowerCase()] ?? 4;
    if (sa !== sb) return sa - sb;
    const confDiff = Number(b.thesis_confidence) - Number(a.thesis_confidence);
    if (confDiff !== 0) return confDiff;
    return Number(b.annual_yield_pct) - Number(a.annual_yield_pct);
  });

  const proposedCount = recommendations.filter((r) => r.status?.toLowerCase() === "proposed").length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Lightbulb size={14} className="text-amber-400" />
          <h2 className="text-sm font-medium text-slate-400">Strategy Recommendations</h2>
        </div>
        <div className="flex items-center gap-2">
          {proposedCount > 0 && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-500/15 text-indigo-400 border border-indigo-500/20">
              {proposedCount} PROPOSED
            </span>
          )}
          <span className="text-[10px] text-slate-600">{recommendations.length} total</span>
        </div>
      </div>

      <div className="space-y-2">
        {sorted.map((r, i) => (
          <RecItem key={`${r.ticker}-${r.strike}-${r.right}-${i}`} rec={r} />
        ))}
      </div>
    </Card>
  );
}
