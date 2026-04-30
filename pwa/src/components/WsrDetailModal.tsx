import { useRef, useState, useMemo } from "react";
import type { WsrSummaryRow } from "../data";
import { X, ChevronLeft, BookOpen } from "lucide-react";
import { marked } from "marked";

function shortDate(d: string): string {
  const s = d.slice(0, 10);
  const [y, m, day] = s.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(day)} ${months[Number(m)]} ${y}`;
}

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

function Paragraphs({ text, className }: { text: string; className?: string }) {
  if (!text) return null;
  const paras = text.split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  return (
    <>
      {paras.map((p, i) => (
        <p key={i} className={className ?? "text-[length:var(--t-sm)] text-slate-200 leading-relaxed"}>
          {p}
        </p>
      ))}
    </>
  );
}

export function WsrDetailModal({
  wsr,
  onClose,
}: {
  wsr: WsrSummaryRow;
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

  const confidence = Number(wsr.confidence) || 0;
  const confPct = Math.round(confidence * 100);
  const regime = REGIME_STYLE[wsr.regime] ?? REGIME_STYLE.neutral;

  // Render full markdown — primary content. Strip H1 title since modal header already shows it.
  const html = useMemo(() => {
    if (!wsr.raw_md) return "";
    let md = wsr.raw_md;
    // Strip the leading `# Title` line — header above already shows the date
    md = md.replace(/^#\s+[^\n]+\n+/, "");
    return marked.parse(md, { breaks: false, gfm: true }) as string;
  }, [wsr.raw_md]);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-[#050916]"
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
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-indigo-400" />
          <div className="text-right">
            <h2 className="text-[length:var(--t-base)] font-bold text-white leading-tight">Weekly Strategy</h2>
            <span className="text-[length:var(--t-2xs)] text-slate-400">{shortDate(wsr.date || "")}</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-400 active:text-white"
          aria-label="Close"
        >
          <X size={18} />
        </button>
      </div>

      {/* Regime + confidence bar */}
      <div className="px-4 py-4 border-b border-white/6 space-y-3">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[length:var(--t-xs)] font-semibold border ${regime.bg} ${regime.text} ${regime.border}`}>
            {regime.label}
          </span>
          <span className="text-[length:var(--t-xs)] text-slate-400">Regime</span>
        </div>
        <div className="flex items-center gap-2.5">
          <span className="text-[length:var(--t-2xs)] text-slate-400 font-bold shrink-0">CONFIDENCE</span>
          <div className="flex-1 h-2 rounded-full bg-white/8 overflow-hidden">
            <div
              className="h-full transition-all"
              style={{
                width: `${confPct}%`,
                background: `linear-gradient(90deg, rgb(var(--accent-rgb)), var(--accent-bright))`,
              }}
            />
          </div>
          <span className="text-[length:var(--t-sm)] font-bold tabular-nums text-white shrink-0">{confPct}%</span>
        </div>
      </div>

      {/* Scrollable body — render the full WSR markdown */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-4 py-4">
        {/* Verdict — primary focus, pulled from structured field */}
        {wsr.verdict && (
          <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/20 p-4 mb-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[length:var(--t-base)]">🎯</span>
              <h3 className="text-[length:var(--t-xs)] uppercase tracking-wider font-bold text-indigo-400">Verdict</h3>
            </div>
            <div className="space-y-2.5">
              <Paragraphs text={wsr.verdict} className="text-[length:var(--t-sm)] text-slate-100 leading-relaxed" />
            </div>
          </div>
        )}

        {/* Full WSR markdown — every section, every table, every bullet */}
        {html ? (
          <div className="wsr-md" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <p className="text-[length:var(--t-sm)] text-slate-500 italic">No full markdown available for this WSR.</p>
        )}

        {/* Toggle to show the raw plaintext source */}
        {wsr.raw_md && (
          <details className="mt-6 pt-4 border-t border-white/5">
            <summary className="cursor-pointer text-[length:var(--t-xs)] font-semibold uppercase tracking-wider text-slate-500 hover:text-white">
              Source markdown
            </summary>
            <pre className="mt-3 p-3 rounded-lg bg-black/30 border border-white/5 text-[length:var(--t-2xs)] text-slate-300 whitespace-pre-wrap leading-relaxed font-mono">
              {wsr.raw_md}
            </pre>
          </details>
        )}

        {/* Footer spacing */}
        <div className="h-6" />
      </div>
    </div>
  );
}
