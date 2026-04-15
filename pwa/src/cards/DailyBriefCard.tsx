import { useState } from "react";
import type { DailyBriefRow } from "../data";
import { Card } from "./Card";
import { Newspaper, ChevronDown } from "lucide-react";
import { SENTIMENT } from "../lib/emojis";

function Skeleton() {
  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="shimmer h-4 w-24" />
        <div className="shimmer h-3 w-20" />
      </div>
      <div className="shimmer h-7 w-28 mb-3" />
      <div className="shimmer h-4 w-full mb-3" />
      <div className="space-y-2">
        <div className="shimmer h-3 w-full" />
        <div className="shimmer h-3 w-5/6" />
        <div className="shimmer h-3 w-4/6" />
      </div>
    </Card>
  );
}

function splitPipe(s: string | undefined): string[] {
  if (!s) return [];
  return s
    .split(/\s*\|\s*/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function Section({
  icon,
  title,
  items,
  text,
}: {
  icon: string;
  title: string;
  items?: string[];
  text?: string;
}) {
  const hasContent = (items && items.length > 0) || !!text;
  if (!hasContent) return null;
  return (
    <div className="pt-3 border-t border-white/5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm">{icon}</span>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{title}</span>
      </div>
      {text && <p className="text-sm text-slate-300 leading-relaxed">{text}</p>}
      {items && items.length > 0 && (
        <ul className="space-y-1.5">
          {items.map((b, i) => (
            <li key={i} className="flex gap-2 text-[13px] text-slate-300 leading-relaxed">
              <span className="text-indigo-400/50 mt-0.5 shrink-0">•</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DailyBriefCard({ row, loading }: { row: DailyBriefRow | null; loading?: boolean }) {
  const [expanded, setExpanded] = useState(true);

  if (loading) return <Skeleton />;

  if (!row) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Newspaper size={16} />
          <span className="text-sm">Daily Brief — no data yet</span>
        </div>
      </Card>
    );
  }

  const chip = SENTIMENT[row.sentiment] ?? SENTIMENT.neutral;
  const bullets = [row.bullet_1, row.bullet_2, row.bullet_3].filter(Boolean);
  const overnight = splitPipe(row.overnight);
  const premarket = splitPipe(row.premarket);
  const catalysts = splitPipe(row.catalysts);
  const watch = splitPipe(row.watch);
  const hasRichContent =
    overnight.length || premarket.length || catalysts.length || watch.length || row.posture;

  return (
    <Card className="glass-bright">
      {/* Header — date left, sentiment chip right */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">⚡</span>
          <h2 className="text-sm font-semibold text-slate-200">Daily Brief</h2>
          <time className="text-xs text-slate-500 tabular-nums ml-1">{(row.date || "").slice(0, 10)}</time>
        </div>
        <div
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${chip.bg} ${chip.text}`}
        >
          <span className="text-[10px]">{chip.emoji}</span>
          <span>{chip.label}</span>
        </div>
      </div>

      {/* Headline (the summary one-liner) */}
      {row.headline && (
        <p className="text-[15px] text-white font-medium leading-snug mb-3">{row.headline}</p>
      )}

      {/* Verdict — the "what do I do" takeaway */}
      {row.verdict && (
        <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/20 px-3 py-2.5 mb-3">
          <div className="flex items-start gap-2">
            <span className="text-sm mt-0.5">🎯</span>
            <div>
              <div className="text-[10px] uppercase tracking-wider font-semibold text-indigo-400 mb-0.5">Verdict</div>
              <p className="text-[13px] text-slate-100 leading-snug">{row.verdict}</p>
            </div>
          </div>
        </div>
      )}

      {/* Key takeaways (bullets) */}
      {bullets.length > 0 && (
        <ul className="space-y-1.5 mb-3">
          {bullets.map((b, i) => (
            <li key={i} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
              <span className="text-indigo-400/60 mt-0.5 shrink-0">•</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Expand/collapse toggle for rich sections */}
      {hasRichContent && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="w-full flex items-center justify-center gap-1.5 py-2 text-xs text-slate-400 hover:text-slate-200 border-t border-white/5"
          >
            <span>{expanded ? "Hide details" : "What it means for you"}</span>
            <ChevronDown size={12} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
          </button>

          {expanded && (
            <div className="flex flex-col gap-3 pt-1">
              <Section icon="🌙" title="Overnight" items={overnight} />
              <Section icon="🌅" title="Pre-Market" items={premarket} />
              <Section icon="📅" title="Today's Catalysts" items={catalysts} />
              <Section icon="📍" title="Posture" text={row.posture} />
              <Section icon="👀" title="Watch List" items={watch} />
            </div>
          )}
        </>
      )}
    </Card>
  );
}
