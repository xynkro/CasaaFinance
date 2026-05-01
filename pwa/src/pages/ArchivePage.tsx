import { lazy, Suspense, useState } from "react";
import type { ArchiveRow, DailyBriefRow } from "../data";
import { Card } from "../cards/Card";
import { FileText, ChevronRight, Archive, Newspaper } from "lucide-react";
import { SENTIMENT } from "../lib/emojis";
import { ArchiveViewer } from "../components/ArchiveViewer";
import { shortDateLong as shortDate } from "../lib/dates";

// Lazy: shared with HomePage so the chunk is reused. Modal renders only
// when a brief row is selected.
const BriefDetailModal = lazy(() =>
  import("../components/BriefDetailModal").then((m) => ({ default: m.BriefDetailModal })),
);

function ArchiveItem({ row, onOpen }: { row: ArchiveRow; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full flex items-center gap-3.5 px-5 py-3.5 hover:bg-white/3 active:bg-white/5 transition-colors text-left"
    >
      <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center shrink-0">
        <FileText size={18} className="text-indigo-400" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[length:var(--t-sm)] font-medium text-slate-200 truncate">{row.title}</div>
        <div className="text-[length:var(--t-xs)] text-slate-500">{shortDate(row.date)}</div>
      </div>
      <ChevronRight size={14} className="text-slate-600 shrink-0" />
    </button>
  );
}

function DailyBriefItem({ row, onOpen }: { row: DailyBriefRow; onOpen: () => void }) {
  const chip = SENTIMENT[row.sentiment] ?? SENTIMENT.neutral;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full px-5 py-3.5 hover:bg-white/3 active:bg-white/5 transition-colors text-left"
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[length:var(--t-xs)] font-semibold text-slate-200 tabular-nums">{shortDate(row.date)}</span>
        <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[length:var(--t-2xs)] font-semibold ${chip.bg} ${chip.text}`}>
          <span className="text-[length:var(--t-2xs)]">{chip.emoji}</span>
          <span>{chip.label}</span>
        </div>
      </div>
      {row.headline && (
        <p className="text-[length:var(--t-sm)] text-slate-200 leading-snug mb-1 font-medium">{row.headline}</p>
      )}
      {row.verdict && (
        <p className="text-[length:var(--t-xs)] text-slate-400 leading-snug">{row.verdict}</p>
      )}
    </button>
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
          <p className="text-[length:var(--t-sm)] font-medium text-slate-400">No reports yet</p>
          <p className="text-[length:var(--t-xs)] text-slate-500 mt-0.5">WSR PDFs and daily briefs will appear here</p>
        </div>
      </div>
    </Card>
  );
}

export function ArchivePage({ archive, dailyHistory }: { archive: ArchiveRow[]; dailyHistory: DailyBriefRow[] }) {
  const [viewingArchive, setViewingArchive] = useState<ArchiveRow | null>(null);
  const [viewingBrief, setViewingBrief] = useState<DailyBriefRow | null>(null);

  if (!archive.length && !dailyHistory.length) {
    return (
      <div className="px-4 pb-4">
        <EmptyState />
      </div>
    );
  }

  return (
    <>
      <div className="px-4 pb-4 flex flex-col gap-4">
        {/* WSR PDFs */}
        {archive.length > 0 && (
          <>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText size={12} className="text-indigo-400" />
                <h3 className="text-[length:var(--t-xs)] font-medium text-slate-500 uppercase tracking-wider">Weekly Strategy Reviews</h3>
              </div>
              <span className="text-[length:var(--t-xs)] text-slate-600">{archive.length}</span>
            </div>
            <div className="glass rounded-2xl overflow-hidden divide-y divide-white/5">
              {archive.map((row, i) => (
                <div key={`${row.drive_file_id}-${i}`} className={`fade-up fade-up-${Math.min(i + 1, 4)}`}>
                  <ArchiveItem row={row} onOpen={() => setViewingArchive(row)} />
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
                <h3 className="text-[length:var(--t-xs)] font-medium text-slate-500 uppercase tracking-wider">Daily Briefs</h3>
              </div>
              <span className="text-[length:var(--t-xs)] text-slate-600">{dailyHistory.length}</span>
            </div>
            <div className="glass rounded-2xl overflow-hidden divide-y divide-white/5">
              {dailyHistory.map((row, i) => (
                <div key={`${row.date}-${i}`} className={`fade-up fade-up-${Math.min(i + 1, 4)}`}>
                  <DailyBriefItem row={row} onOpen={() => setViewingBrief(row)} />
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {viewingArchive && (
        <ArchiveViewer row={viewingArchive} onClose={() => setViewingArchive(null)} />
      )}
      {viewingBrief && (
        <Suspense fallback={null}>
          <BriefDetailModal row={viewingBrief} onClose={() => setViewingBrief(null)} />
        </Suspense>
      )}
    </>
  );
}
