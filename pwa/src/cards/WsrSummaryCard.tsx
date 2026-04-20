import type { WsrSummaryRow } from "../data";
import { Card } from "./Card";
import { BookOpen, Sparkles, Target, Activity } from "lucide-react";
import { useState } from "react";

const REGIME_COLOR: Record<string, string> = {
  bull_early_cycle:  "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  bull_mid_cycle:    "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  bull_late_cycle:   "text-amber-400 bg-amber-500/10 border-amber-500/30",
  neutral:           "text-slate-300 bg-slate-500/10 border-slate-500/30",
  bear_early:        "text-red-400 bg-red-500/10 border-red-500/30",
  bear_mid:          "text-red-400 bg-red-500/10 border-red-500/30",
  bear_late:         "text-red-400 bg-red-500/10 border-red-500/30",
  risk_off:          "text-red-400 bg-red-500/10 border-red-500/30",
};

function fmtRegime(r: string): string {
  if (!r) return "—";
  return r.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function WsrSummaryCard({ wsr }: { wsr: WsrSummaryRow | null }) {
  const [expanded, setExpanded] = useState(false);

  if (!wsr) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <BookOpen size={14} />
          <span className="text-sm">No WSR yet</span>
        </div>
      </Card>
    );
  }

  const confidence = Number(wsr.confidence) || 0;
  const confPct = Math.round(confidence * 100);
  const regimeStyle = REGIME_COLOR[wsr.regime] ?? REGIME_COLOR.neutral;
  const dateStr = wsr.date?.split("T")[0] ?? "";

  return (
    <div className="glass-accent rounded-2xl p-5 space-y-3.5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen size={14} style={{ color: "var(--accent)" }} />
          <h2 className="text-sm font-semibold text-slate-100">This Week</h2>
          <span className="text-[10px] text-slate-400">{dateStr}</span>
        </div>
        <div className={`px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide border ${regimeStyle}`}>
          {fmtRegime(wsr.regime)}
        </div>
      </div>

      {/* Verdict — the headline */}
      <p className="text-[13px] text-slate-100 leading-relaxed font-medium">
        {wsr.verdict}
      </p>

      {/* Confidence bar */}
      <div className="flex items-center gap-2.5">
        <span className="text-[10px] text-slate-400 font-semibold shrink-0">CONFIDENCE</span>
        <div className="flex-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
          <div
            className="h-full transition-all"
            style={{
              width: `${confPct}%`,
              background: `linear-gradient(90deg, rgb(var(--accent-rgb)), var(--accent-bright))`,
            }}
          />
        </div>
        <span className="text-xs font-bold tabular-nums text-slate-200 shrink-0">{confPct}%</span>
      </div>

      {/* Key sections as pills */}
      <div className="grid grid-cols-1 gap-2">
        {wsr.action_summary && (
          <div className="flex items-start gap-2 text-[11px]">
            <Target size={11} className="text-emerald-400 mt-0.5 shrink-0" />
            <div>
              <span className="text-emerald-400 font-semibold">ACTION · </span>
              <span className="text-slate-200">{wsr.action_summary}</span>
            </div>
          </div>
        )}
        {wsr.options_summary && (
          <div className="flex items-start gap-2 text-[11px]">
            <Sparkles size={11} className="text-amber-400 mt-0.5 shrink-0" />
            <div>
              <span className="text-amber-400 font-semibold">OPTIONS · </span>
              <span className="text-slate-200">{wsr.options_summary}</span>
            </div>
          </div>
        )}
        {wsr.macro_read && (
          <div className="flex items-start gap-2 text-[11px]">
            <Activity size={11} className="text-cyan-400 mt-0.5 shrink-0" />
            <div>
              <span className="text-cyan-400 font-semibold">MACRO · </span>
              <span className="text-slate-300">{wsr.macro_read}</span>
            </div>
          </div>
        )}
      </div>

      {/* Expand */}
      {wsr.raw_md && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="w-full mt-1 py-1.5 rounded-lg text-[10px] text-slate-400 hover:text-slate-200 border border-white/5 hover:border-white/10 transition-all"
        >
          {expanded ? "Hide full WSR" : "Show full WSR ↓"}
        </button>
      )}
      {expanded && wsr.raw_md && (
        <div className="mt-2 p-3 rounded-lg bg-black/30 border border-white/5 max-h-[50vh] overflow-y-auto">
          <pre className="text-[10px] text-slate-300 whitespace-pre-wrap leading-relaxed font-mono">
            {wsr.raw_md}
          </pre>
        </div>
      )}
    </div>
  );
}
