import type { ArchiveRow, DailyBriefRow } from "../data";
import { Card } from "../cards/Card";
import { FileText, ExternalLink, Archive, Newspaper } from "lucide-react";

function shortDate(d: string): string {
  const s = d.slice(0, 10);
  const [y, m, day] = s.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(day)} ${months[Number(m)]} ${y}`;
}

const SENTIMENT_CHIP: Record<string, { emoji: string; color: string }> = {
  bullish: { emoji: "\u{1F7E2}", color: "text-emerald-400" },
  neutral: { emoji: "\u{1F7E1}", color: "text-yellow-400" },
  bearish: { emoji: "\u{1F534}", color: "text-red-400" },
};

function ArchiveItem({ row }: { row: ArchiveRow }) {
  const url = row.drive_url || `https://drive.google.com/file/d/${row.drive_file_id}/view`;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3.5 px-5 py-3.5 hover:bg-white/3 active:bg-white/5 transition-colors"
    >
      <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center shrink-0">
        <FileText size={18} className="text-indigo-400" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-200 truncate">{row.title}</div>
        <div className="text-xs text-slate-500">{shortDate(row.date)}</div>
      </div>
      <ExternalLink size={14} className="text-slate-600 shrink-0" />
    </a>
  );
}

function DailyBriefItem({ row }: { row: DailyBriefRow }) {
  const chip = SENTIMENT_CHIP[row.sentiment] ?? SENTIMENT_CHIP.neutral;
  return (
    <div className="px-5 py-3.5">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs">{chip.emoji}</span>
          <span className={`text-xs font-semibold capitalize ${chip.color}`}>{row.sentiment}</span>
        </div>
        <span className="text-xs text-slate-500">{shortDate(row.date)}</span>
      </div>
      <p className="text-sm text-slate-300 leading-snug">{row.verdict}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-6">
        <div className="w-12 h-12 rounded-2xl bg-slate-700/50 flex items-center justify-center">
          <Archive size={20} className="text-slate-500" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-slate-400">No reports yet</p>
          <p className="text-xs text-slate-500 mt-0.5">WSR PDFs and daily briefs will appear here</p>
        </div>
      </div>
    </Card>
  );
}

export function ArchivePage({ archive, dailyHistory }: { archive: ArchiveRow[]; dailyHistory: DailyBriefRow[] }) {
  if (!archive.length && !dailyHistory.length) {
    return (
      <div className="px-4 pb-4">
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="px-4 pb-4 flex flex-col gap-4">
      {/* WSR PDFs */}
      {archive.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText size={12} className="text-indigo-400" />
              <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">Weekly Strategy Reviews</h3>
            </div>
            <span className="text-xs text-slate-600">{archive.length}</span>
          </div>
          <div className="glass rounded-2xl overflow-hidden divide-y divide-white/5">
            {archive.map((row, i) => (
              <div key={`${row.drive_file_id}-${i}`} className={`fade-up fade-up-${Math.min(i + 1, 4)}`}>
                <ArchiveItem row={row} />
              </div>
            ))}
          </div>
        </>
      )}

      {/* Daily Briefs history */}
      {dailyHistory.length > 0 && (
        <>
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-2">
              <Newspaper size={12} className="text-indigo-400" />
              <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">Daily Briefs</h3>
            </div>
            <span className="text-xs text-slate-600">{dailyHistory.length}</span>
          </div>
          <div className="glass rounded-2xl overflow-hidden divide-y divide-white/5">
            {dailyHistory.map((row, i) => (
              <div key={`${row.date}-${i}`} className={`fade-up fade-up-${Math.min(i + 1, 4)}`}>
                <DailyBriefItem row={row} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
