import type { DailyBriefRow } from "../data";
import { Card } from "./Card";

const CHIP: Record<string, { emoji: string; color: string }> = {
  bullish: { emoji: "\u{1F7E2}", color: "text-emerald-400" },
  neutral: { emoji: "\u{1F7E1}", color: "text-yellow-400" },
  bearish: { emoji: "\u{1F534}", color: "text-red-400" },
};

export function DailyBriefCard({ row }: { row: DailyBriefRow | null }) {
  if (!row) {
    return (
      <Card>
        <p className="text-sm text-slate-500">Daily Brief — no data yet</p>
      </Card>
    );
  }

  const chip = CHIP[row.sentiment] ?? CHIP.neutral;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-slate-400">Daily Brief</h2>
        <time className="text-xs text-slate-500">{row.date}</time>
      </div>

      <div className={`flex items-center gap-2 mb-3 text-base font-semibold ${chip.color}`}>
        <span>{chip.emoji}</span>
        <span className="capitalize">{row.sentiment}</span>
      </div>

      <p className="text-sm text-slate-200 mb-2 font-medium">{row.verdict}</p>

      <ul className="space-y-1.5 text-sm text-slate-300">
        {[row.bullet_1, row.bullet_2, row.bullet_3].filter(Boolean).map((b, i) => (
          <li key={i} className="leading-snug">
            <span className="text-slate-500 mr-1.5">&bull;</span>
            {b}
          </li>
        ))}
      </ul>
    </Card>
  );
}
