import type { WsrSummaryRow } from "../data";
import { Card } from "./Card";
import { BookOpen, Sparkles, Target, Activity, AlertTriangle, ChevronRight } from "lucide-react";
import { useState } from "react";

const REGIME_STYLE: Record<string, { bg: string; text: string; border: string; label: string }> = {
  bull_early_cycle: { bg: "bg-emerald-500/12", text: "text-emerald-400", border: "border-emerald-500/30", label: "Bull · Early" },
  bull_mid_cycle:   { bg: "bg-emerald-500/12", text: "text-emerald-400", border: "border-emerald-500/30", label: "Bull · Mid" },
  bull_late_cycle:  { bg: "bg-amber-500/12",   text: "text-amber-400",   border: "border-amber-500/30",   label: "Bull · Late" },
  neutral:          { bg: "bg-slate-500/12",   text: "text-slate-300",   border: "border-slate-500/30",   label: "Neutral" },
  bear_early:       { bg: "bg-red-500/12",     text: "text-red-400",     border: "border-red-500/30",     label: "Bear · Early" },
  bear_mid:         { bg: "bg-red-500/12",     text: "text-red-400",     border: "border-red-500/30",     label: "Bear · Mid" },
  bear_late:        { bg: "bg-red-500/12",     text: "text-red-400",     border: "border-red-500/30",     label: "Bear · Late" },
  risk_off:         { bg: "bg-red-500/12",     text: "text-red-400",     border: "border-red-500/30",     label: "Risk Off" },
};

/**
 * Render a paragraph-rich text string. Splits on double newlines into paragraphs
 * and renders each as a <p> with the given classes.
 */
function Paragraphs({ text, className }: { text: string; className?: string }) {
  if (!text) return null;
  const paras = text.split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  return (
    <>
      {paras.map((p, i) => (
        <p key={i} className={className ?? "text-sm text-slate-200 leading-relaxed"}>
          {p}
        </p>
      ))}
    </>
  );
}

function Section({
  icon: Icon,
  color,
  label,
  text,
}: {
  icon: typeof Target;
  color: string;
  label: string;
  text: string;
}) {
  if (!text) return null;
  return (
    <div className="border-t border-white/5 pt-3.5">
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={12} className={color} />
        <div className={`text-[10px] uppercase tracking-wider font-bold ${color}`}>
          {label}
        </div>
      </div>
      <div className="space-y-2">
        <Paragraphs text={text} className="text-sm text-slate-200 leading-relaxed" />
      </div>
    </div>
  );
}

export function WsrSummaryCard({ wsr }: { wsr: WsrSummaryRow | null }) {
  const [expanded, setExpanded] = useState(false);

  if (!wsr) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <BookOpen size={16} />
          <span className="text-sm">No WSR yet</span>
        </div>
      </Card>
    );
  }

  const confidence = Number(wsr.confidence) || 0;
  const confPct = Math.round(confidence * 100);
  const regime = REGIME_STYLE[wsr.regime] ?? REGIME_STYLE.neutral;
  const dateStr = (wsr.date || "").split("T")[0];

  return (
    <Card className="glass-bright">
      {/* Header — matches DailyBriefCard */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">📘</span>
          <h2 className="text-sm font-semibold text-slate-200">Weekly Strategy</h2>
          <time className="text-xs text-slate-500 tabular-nums ml-1">{dateStr}</time>
        </div>
        <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${regime.bg} ${regime.text} ${regime.border}`}>
          <span>{regime.label}</span>
        </div>
      </div>

      {/* Confidence bar */}
      <div className="flex items-center gap-2.5 mb-3">
        <span className="text-[10px] text-slate-400 font-bold shrink-0">CONFIDENCE</span>
        <div className="flex-1 h-2 rounded-full bg-white/8 overflow-hidden">
          <div
            className="h-full transition-all"
            style={{
              width: `${confPct}%`,
              background: `linear-gradient(90deg, rgb(var(--accent-rgb)), var(--accent-bright))`,
            }}
          />
        </div>
        <span className="text-sm font-bold tabular-nums text-white shrink-0">{confPct}%</span>
      </div>

      {/* Verdict box — matches DailyBrief's verdict visual */}
      {wsr.verdict && (
        <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/20 px-3 py-2.5 mb-3">
          <div className="flex items-start gap-2">
            <span className="text-sm mt-0.5">🎯</span>
            <div className="flex-1 min-w-0 space-y-2">
              <div className="text-[10px] uppercase tracking-wider font-bold text-indigo-400 mb-0.5">Verdict</div>
              <Paragraphs text={wsr.verdict} className="text-[13px] text-slate-100 leading-relaxed" />
            </div>
          </div>
        </div>
      )}

      {/* Rich body — only shown when expanded for the full strategy depth */}
      {expanded && (
        <div className="space-y-3.5">
          <Section icon={Target} color="text-emerald-400" label="Action Plan" text={wsr.action_summary} />
          <Section icon={Sparkles} color="text-amber-400" label="Options Book" text={wsr.options_summary} />
          <Section icon={Activity} color="text-cyan-400" label="Macro Regime Read" text={wsr.macro_read} />
          <Section icon={AlertTriangle} color="text-red-400" label="Red Team Flags" text={wsr.redteam_summary} />
          {wsr.week_events && (
            <div className="border-t border-white/5 pt-3.5">
              <div className="flex items-center gap-1.5 mb-2">
                <Activity size={12} className="text-slate-400" />
                <div className="text-[10px] uppercase tracking-wider font-bold text-slate-400">
                  Week Lookback
                </div>
              </div>
              <ul className="space-y-1.5">
                {wsr.week_events.split(/\s*\|\s*/).filter(Boolean).map((ev, i) => (
                  <li key={i} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
                    <span className="text-slate-500 mt-0.5 shrink-0">•</span>
                    <span>{ev}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {wsr.raw_md && (
            <details className="border-t border-white/5 pt-3.5">
              <summary className="cursor-pointer text-[10px] uppercase tracking-wider font-bold text-slate-400 hover:text-slate-200">
                Full raw markdown ↓
              </summary>
              <div className="mt-2 p-3 rounded-lg bg-black/30 border border-white/5 max-h-[60vh] overflow-y-auto">
                <pre className="text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed font-mono">
                  {wsr.raw_md}
                </pre>
              </div>
            </details>
          )}
        </div>
      )}

      {/* Expand affordance (matches DailyBrief's "Read full brief →") */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center justify-center gap-1 w-full pt-3 mt-2 border-t border-white/5 text-xs text-indigo-400 font-medium hover:text-indigo-300 transition-colors"
      >
        <span>{expanded ? "Collapse" : "Read full strategy"}</span>
        <ChevronRight size={13} className={`transition-transform ${expanded ? "rotate-90" : ""}`} />
      </button>
    </Card>
  );
}
