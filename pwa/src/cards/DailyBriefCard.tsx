import type { DailyBriefRow } from "../data";
import { Card } from "./Card";
import { Newspaper, ChevronRight, Calendar, BarChart3, AlertTriangle, Users, Landmark } from "lucide-react";
import { SENTIMENT } from "../lib/emojis";

function Skeleton() {
  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="shimmer h-4 w-28" />
        <div className="shimmer h-5 w-20" />
      </div>
      <div className="space-y-2">
        <div className="shimmer h-4 w-full" />
        <div className="shimmer h-4 w-5/6" />
        <div className="shimmer h-4 w-4/6" />
      </div>
    </Card>
  );
}

function truncate(s: string | undefined, n = 240): string {
  if (!s) return "";
  const cleaned = s.trim();
  if (cleaned.length <= n) return cleaned;
  return cleaned.slice(0, n - 1).trim() + "…";
}

function ChipRow({ icon: Icon, color, items }: {
  icon: typeof Calendar;
  color: string;
  items?: string;
}) {
  if (!items) return null;
  const chips = items.split("|").map((s) => s.trim()).filter(Boolean);
  if (!chips.length) return null;
  return (
    <div className="flex items-start gap-1.5 mt-2">
      <Icon size={12} className={`${color} shrink-0 mt-0.5`} />
      <div className="flex flex-wrap gap-1">
        {chips.map((c, i) => (
          <span key={i} className="inline-block px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] bg-white/5 text-slate-300 leading-tight">
            {c}
          </span>
        ))}
      </div>
    </div>
  );
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
          <span className="text-[length:var(--t-sm)]">Daily Brief — no data yet</span>
        </div>
      </Card>
    );
  }

  const chip = SENTIMENT[row.sentiment] ?? SENTIMENT.neutral;
  // Pick the strongest summary line available. Priority: headline > verdict > bullet_1.
  const summaryText = truncate(row.headline || row.verdict || row.bullet_1 || "", 240);

  return (
    <Card variant="bright">
      <button
        type="button"
        onClick={onOpen}
        className="block w-full text-left active:opacity-80 transition-opacity"
        aria-label="Open full daily brief"
      >
        {/* Header — matches Weekly Strategy card exactly */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-[length:var(--t-base)]">⚡</span>
            <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Daily Brief</h2>
            <time className="text-[length:var(--t-xs)] text-slate-500 tabular-nums ml-1">{(row.date || "").slice(0, 10)}</time>
          </div>
          <div
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[length:var(--t-xs)] font-semibold ${chip.bg} ${chip.text}`}
          >
            <span className="text-[length:var(--t-2xs)]">{chip.emoji}</span>
            <span>{chip.label}</span>
          </div>
        </div>

        {/* 3-line summary */}
        {summaryText && (
          <p className="text-[length:var(--t-sm)] text-slate-100 leading-relaxed line-clamp-3">
            {summaryText}
          </p>
        )}

        {/* Structured chips — Finnhub-sourced data rendered as compact tags */}
        <ChipRow icon={Calendar} color="text-blue-400" items={row.earnings_today} />
        <ChipRow icon={BarChart3} color="text-cyan-400" items={row.macro_today} />
        <ChipRow icon={AlertTriangle} color="text-red-400" items={row.negative_news} />
        <ChipRow icon={Users} color="text-amber-400" items={row.insider_alert} />
        <ChipRow icon={Landmark} color="text-violet-400" items={row.gov_confluence} />

        {/* Tap-to-expand affordance */}
        {onOpen && (
          <div className="flex items-center justify-center gap-1 pt-3 mt-3 border-t border-white/5 text-[length:var(--t-xs)] text-indigo-400 font-medium">
            <span>Open full brief</span>
            <ChevronRight size={13} />
          </div>
        )}
      </button>
    </Card>
  );
}
