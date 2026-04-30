import { useRef, useState } from "react";
import type { ArchiveRow } from "../data";
import { X, ChevronLeft, ExternalLink } from "lucide-react";

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
  const touchRef = useRef<{ startX: number; startY: number; moving: boolean }>({
    startX: 0, startY: 0, moving: false,
  });
  const [dragX, setDragX] = useState(0);

  const SWIPE_THRESHOLD = 80;

  const onTouchStart = (e: React.TouchEvent) => {
    touchRef.current = {
      startX: e.touches[0].clientX,
      startY: e.touches[0].clientY,
      moving: false,
    };
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchRef.current.startX;
    const dy = e.touches[0].clientY - touchRef.current.startY;
    if (!touchRef.current.moving) {
      if (Math.abs(dy) > Math.abs(dx)) return;
      if (Math.abs(dx) < 10) return;
      if (dx <= 0) return;
      touchRef.current.moving = true;
    }
    if (touchRef.current.moving && dx > 0) {
      setDragX(dx);
    }
  };

  const onTouchEnd = () => {
    if (touchRef.current.moving && dragX > SWIPE_THRESHOLD) {
      onClose();
    } else {
      setDragX(0);
    }
    touchRef.current.moving = false;
  };

  const previewUrl = `https://drive.google.com/file/d/${row.drive_file_id}/preview`;
  const externalUrl = row.drive_url || `https://drive.google.com/file/d/${row.drive_file_id}/view`;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[#050a18] transition-transform"
      style={{
        transform: `translateX(${dragX}px)`,
        transitionDuration: touchRef.current.moving ? "0ms" : "250ms",
        opacity: 1 - Math.min(dragX / 400, 0.3),
      }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
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
