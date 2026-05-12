import { useState } from "react";
import type { GovConfluenceRow } from "../data";
import { Card } from "./Card";
import { Landmark, ChevronDown, ChevronUp } from "lucide-react";

function fmtScore(v: string | number): number {
  const n = Number(v);
  return isNaN(n) ? 0 : Math.round(n);
}

function TierBadge({ tier }: { tier: string }) {
  if (!tier) return null;
  const color = tier === "A"
    ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
    : "bg-amber-500/20 text-amber-400 border-amber-500/30";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${color}`}>
      {tier}
    </span>
  );
}

function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const color = value >= 50 ? "#10b981" : value >= 30 ? "#f59e0b" : "#64748b";
  return (
    <div className="h-1.5 rounded-full bg-white/5 flex-1 min-w-[40px]">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  );
}

function SignalRow({ row }: { row: GovConfluenceRow }) {
  const [expanded, setExpanded] = useState(false);
  const score = fmtScore(row.confluence_score);
  const contract = fmtScore(row.contract_score);
  const congress = fmtScore(row.congress_score);
  const insider = fmtScore(row.insider_score);
  const analyst = fmtScore(row.analyst_score);

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className="w-full text-left glass rounded-xl p-3 active:bg-white/3 transition-colors space-y-1.5"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker}</span>
          <TierBadge tier={row.tier} />
          {row.recommended_strategy && (
            <span className="text-[length:var(--t-2xs)] font-semibold text-indigo-300 uppercase">
              {row.recommended_strategy}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[length:var(--t-sm)] font-bold tabular-nums ${
            score >= 50 ? "text-emerald-400" : score >= 30 ? "text-amber-400" : "text-slate-400"
          }`}>
            {score}
          </span>
          <ScoreBar value={score} />
        </div>
      </div>

      {row.thesis_oneliner && (
        <p className="text-[length:var(--t-2xs)] text-slate-400 leading-relaxed line-clamp-2">
          {row.thesis_oneliner}
        </p>
      )}

      {expanded && (
        <div className="pt-2 border-t border-white/5 space-y-1.5">
          <div className="grid grid-cols-4 gap-1.5 text-[length:var(--t-2xs)]">
            <div>
              <div className="text-slate-600">Contract</div>
              <div className="tabular-nums text-slate-300 font-semibold">{contract}</div>
            </div>
            <div>
              <div className="text-slate-600">Congress</div>
              <div className="tabular-nums text-slate-300 font-semibold">{congress}</div>
            </div>
            <div>
              <div className="text-slate-600">Insider</div>
              <div className="tabular-nums text-slate-300 font-semibold">{insider}</div>
            </div>
            <div>
              <div className="text-slate-600">Analyst</div>
              <div className="tabular-nums text-slate-300 font-semibold">{analyst}</div>
            </div>
          </div>
          {row.recommended_action && (
            <p className="text-[length:var(--t-2xs)] text-slate-500">{row.recommended_action}</p>
          )}
        </div>
      )}
    </button>
  );
}

export function GovConfluenceCard({ signals }: { signals: GovConfluenceRow[] }) {
  const [showAll, setShowAll] = useState(false);

  if (!signals.length) return null;

  const display = showAll ? signals : signals.slice(0, 5);
  const hasMore = signals.length > 5;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Landmark size={14} className="text-violet-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Gov Confluence</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">
          {signals.length} signal{signals.length !== 1 ? "s" : ""}
        </span>
      </div>

      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
        Contracts + congress trades + insider buys + analyst consensus. Score {"≥"} 10 shown.
      </p>

      <div className="space-y-2">
        {display.map((s) => (
          <SignalRow key={`${s.date}-${s.ticker}`} row={s} />
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="flex items-center justify-center gap-1 w-full pt-3 mt-3 border-t border-white/5 text-[length:var(--t-xs)] text-indigo-400 font-medium"
        >
          <span>{showAll ? "Show less" : `Show all ${signals.length}`}</span>
          {showAll ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      )}
    </Card>
  );
}
