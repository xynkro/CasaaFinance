import type { ArchiveRow } from "../data";
import { X, ChevronLeft, ExternalLink } from "lucide-react";
import { useSwipeToDismiss } from "../lib/useSwipeToDismiss";

function shortDate(d: string): string {
  const s = d.slice(0, 10);
  const [y, m, day] = s.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(day)} ${months[Number(m)]} ${y}`;
}

export function ArchiveViewer({
  row,
  onClose,
}: {
  row: ArchiveRow;
  onClose: () => void;
}) {
  const { panelStyle, backdropStyle, handlers } = useSwipeToDismiss({ onDismiss: onClose });

  const previewUrl = `https://drive.google.com/file/d/${row.drive_file_id}/preview`;
  const externalUrl = row.drive_url || `https://drive.google.com/file/d/${row.drive_file_id}/view`;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[#050a18]"
      style={{ ...panelStyle, ...backdropStyle }}
      {...handlers}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 pt-safe-top border-b border-white/6">
        <button
          onClick={onClose}
          className="flex items-center gap-1 pr-2 py-2 text-indigo-400 active:text-indigo-300"
          aria-label="Back"
        >
          <ChevronLeft size={20} />
          <span className="text-[length:var(--t-sm)]">Back</span>
        </button>
        <div className="flex items-center gap-2 min-w-0 px-2">
          <span className="text-[length:var(--t-lg)] shrink-0">📄</span>
          <div className="text-right min-w-0">
            <h2 className="text-[length:var(--t-sm)] font-bold text-white leading-tight truncate max-w-[50vw]">{row.title}</h2>
            <time className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">{shortDate(row.date)}</time>
          </div>
        </div>
        <a
          href={externalUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="p-2 rounded-lg text-slate-500 active:text-white"
          aria-label="Open in Drive"
        >
          <ExternalLink size={16} />
        </a>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-500 active:text-white"
          aria-label="Close"
        >
          <X size={18} />
        </button>
      </div>

      {/* PDF preview via Drive iframe */}
      <div className="flex-1 min-h-0 bg-black">
        <iframe
          src={previewUrl}
          className="w-full h-full border-0"
          title={row.title}
          allow="autoplay"
        />
      </div>
    </div>
  );
}
