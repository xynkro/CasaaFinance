import type { DailyBriefRow } from "../data";
import { Card } from "./Card";
import { Newspaper, ChevronRight } from "lucide-react";
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
  return s.split(/\s*\|\s*/).map((x) => x.trim()).filter(Boolean);
}

export function DailyBriefCard({
  row,
  loading,
  onOpen,
}: {
  row: DailyBriefRow | null;
  loading?: boolean;
  onOpen?: () => void;
}) {
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
  const hasRich =
    splitPipe(row.overnight).length ||
    splitPipe(row.premarket).length ||
    splitPipe(row.catalysts).length ||
    splitPipe(row.watch).length ||
    row.posture ||
    row.raw_md;

  return (
    <Card className="glass-bright">
      <button
        type="button"
        onClick={onOpen}
        className="block w-full text-left active:opacity-80 transition-opacity"
        aria-label="Open full daily brief"
      >
        {/* Header — title/date left, sentiment chip right */}
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

        {/* Headline */}
        {row.headline && (
          <p className="text-[15px] text-white font-medium leading-snug mb-3">{row.headline}</p>
        )}

        {/* Verdict */}
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

        {/* Key takeaways */}
        {bullets.length > 0 && (
          <ul className="space-y-1.5 mb-2">
            {bullets.map((b, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
                <span className="text-indigo-400/60 mt-0.5 shrink-0">•</span>
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Tap-to-expand affordance */}
        {hasRich && (
          <div className="flex items-center justify-center gap-1 pt-2 mt-1 border-t border-white/5 text-xs text-indigo-400 font-medium">
            <span>Read full brief</span>
            <ChevronRight size={13} />
          </div>
        )}
      </button>
    </Card>
  );
}
