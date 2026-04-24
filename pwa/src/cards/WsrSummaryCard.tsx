import type { WsrSummaryRow } from "../data";
import { Card } from "./Card";
import { BookOpen, ChevronRight } from "lucide-react";

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

function firstSentence(text: string, maxChars = 240): string {
  if (!text) return "";
  // Strip paragraph breaks — we want a single flowing summary line
  const flat = text.replace(/\n\n+/g, " ").trim();
  // Grab first sentence if short enough
  const m = flat.match(/^(.+?[.!?])\s/);
  if (m && m[1].length <= maxChars) return m[1];
  if (flat.length > maxChars) return flat.slice(0, maxChars - 1).trim() + "…";
  return flat;
}

function Skeleton() {
  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="shimmer h-4 w-32" />
        <div className="shimmer h-5 w-20" />
      </div>
      <div className="shimmer h-2 w-full mb-3" />
      <div className="space-y-2">
        <div className="shimmer h-4 w-full" />
        <div className="shimmer h-4 w-5/6" />
        <div className="shimmer h-4 w-4/6" />
      </div>
    </Card>
  );
}

export function WsrSummaryCard({
  wsr,
  loading,
  onOpen,
}: {
  wsr: WsrSummaryRow | null;
  loading?: boolean;
  onOpen?: () => void;
}) {
  if (loading) return <Skeleton />;

  if (!wsr) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <BookOpen size={16} />
          <span className="text-sm">Weekly Strategy — no data yet</span>
        </div>
      </Card>
    );
  }

  const confidence = Number(wsr.confidence) || 0;
  const confPct = Math.round(confidence * 100);
  const regime = REGIME_STYLE[wsr.regime] ?? REGIME_STYLE.neutral;
  const dateStr = (wsr.date || "").split("T")[0];
  const verdictBrief = firstSentence(wsr.verdict, 240);

  return (
    <Card variant="bright">
      <button
        type="button"
        onClick={onOpen}
        className="block w-full text-left active:opacity-80 transition-opacity"
        aria-label="Open full WSR"
      >
        {/* Header — identical styling to Daily Brief */}
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

        {/* Confidence bar — compact */}
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] text-slate-400 font-semibold shrink-0">CONF</span>
          <div className="flex-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
            <div
              className="h-full transition-all"
              style={{
                width: `${confPct}%`,
                background: `linear-gradient(90deg, rgb(var(--accent-rgb)), var(--accent-bright))`,
              }}
            />
          </div>
          <span className="text-xs font-bold tabular-nums text-slate-100 shrink-0">{confPct}%</span>
        </div>

        {/* 3-5 line summary: verdict excerpt */}
        {verdictBrief && (
          <p className="text-sm text-slate-100 leading-relaxed line-clamp-3">
            {verdictBrief}
          </p>
        )}

        {/* Tap-to-expand affordance */}
        {onOpen && (
          <div className="flex items-center justify-center gap-1 pt-3 mt-3 border-t border-white/5 text-xs text-indigo-400 font-medium">
            <span>Open full strategy</span>
            <ChevronRight size={13} />
          </div>
        )}
      </button>
    </Card>
  );
}
