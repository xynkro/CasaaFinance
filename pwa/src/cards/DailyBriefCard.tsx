import type { DailyBriefRow } from "../data";
import { Card } from "./Card";
import { Newspaper } from "lucide-react";

const CHIP: Record<string, { emoji: string; label: string; bg: string; text: string; glow: string }> = {
  bullish: { emoji: "\u{1F7E2}", label: "Bullish", bg: "bg-emerald-500/15", text: "text-emerald-400", glow: "glow-green" },
  neutral: { emoji: "\u{1F7E1}", label: "Neutral", bg: "bg-yellow-500/15", text: "text-yellow-400", glow: "glow-yellow" },
  bearish: { emoji: "\u{1F534}", label: "Bearish", bg: "bg-red-500/15", text: "text-red-400", glow: "glow-red" },
};

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

export function DailyBriefCard({ row, loading }: { row: DailyBriefRow | null; loading?: boolean }) {
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

  const chip = CHIP[row.sentiment] ?? CHIP.neutral;

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Newspaper size={14} className="text-slate-500" />
          <h2 className="text-sm font-medium text-slate-400">Daily Brief</h2>
        </div>
        <time className="text-xs text-slate-500 tabular-nums">{row.date}</time>
      </div>

      <div
        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-semibold mb-4 ${chip.bg} ${chip.text} ${chip.glow}`}
      >
        <span>{chip.emoji}</span>
        <span>{chip.label}</span>
      </div>

      <p className="text-[15px] text-slate-100 mb-3 font-medium leading-snug">{row.verdict}</p>

      <ul className="space-y-2">
        {[row.bullet_1, row.bullet_2, row.bullet_3].filter(Boolean).map((b, i) => (
          <li key={i} className="flex gap-2 text-sm text-slate-300 leading-relaxed">
            <span className="text-indigo-400/60 mt-0.5 shrink-0">&bull;</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
