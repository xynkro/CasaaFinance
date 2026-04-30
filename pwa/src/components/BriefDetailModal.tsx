import { useRef, useState } from "react";
import type { DailyBriefRow } from "../data";
import { X, ChevronLeft } from "lucide-react";
import { SENTIMENT } from "../lib/emojis";

function splitPipe(s: string | undefined): string[] {
  if (!s) return [];
  return s.split(/\s*\|\s*/).map((x) => x.trim()).filter(Boolean);
}

function shortDate(d: string): string {
  const s = d.slice(0, 10);
  const [y, m, day] = s.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(day)} ${months[Number(m)]} ${y}`;
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
    <section className="pt-4 border-t border-white/5">
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-[length:var(--t-base)]">{icon}</span>
        <h3 className="text-[length:var(--t-xs)] font-semibold uppercase tracking-wider text-slate-400">{title}</h3>
      </div>
      {text && <p className="text-[length:var(--t-sm)] text-slate-200 leading-relaxed">{text}</p>}
      {items && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((b, i) => (
            <li key={i} className="flex gap-2.5 text-[length:var(--t-sm)] text-slate-200 leading-relaxed">
              <span className="text-indigo-400/60 mt-1 shrink-0">•</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function BriefDetailModal({
  row,
  onClose,
}: {
  row: DailyBriefRow;
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

  const chip = SENTIMENT[row.sentiment] ?? SENTIMENT.neutral;
  const bullets = [row.bullet_1, row.bullet_2, row.bullet_3].filter(Boolean);
  const overnight = splitPipe(row.overnight);
  const premarket = splitPipe(row.premarket);
  const catalysts = splitPipe(row.catalysts);
  const commodities = splitPipe(row.commodities);
  const watch = splitPipe(row.watch);

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
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-lg)]">⚡</span>
          <div className="text-right">
            <h2 className="text-[length:var(--t-sm)] font-bold text-white leading-tight">Daily Brief</h2>
            <time className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">{shortDate(row.date)}</time>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 rounded-lg text-slate-500 active:text-white"
          aria-label="Close"
        >
          <X size={18} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        <div className="px-4 py-4 flex flex-col gap-4">
          {/* Sentiment + headline */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[length:var(--t-xs)] font-semibold ${chip.bg} ${chip.text}`}>
                <span className="text-[length:var(--t-2xs)]">{chip.emoji}</span>
                <span>{chip.label}</span>
              </div>
            </div>
            {row.headline && (
              <p className="text-[length:var(--t-lg)] text-white font-semibold leading-snug">{row.headline}</p>
            )}
          </div>

          {/* Verdict — the "what do I do" takeaway */}
          {row.verdict && (
            <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/20 px-4 py-3">
              <div className="flex items-start gap-2.5">
                <span className="text-[length:var(--t-base)] mt-0.5">🎯</span>
                <div>
                  <div className="text-[length:var(--t-2xs)] uppercase tracking-wider font-semibold text-indigo-400 mb-1">Verdict</div>
                  <p className="text-[length:var(--t-sm)] text-slate-100 leading-snug">{row.verdict}</p>
                </div>
              </div>
            </div>
          )}

          {/* Key bullets */}
          {bullets.length > 0 && (
            <div className="rounded-xl bg-white/[0.02] border border-white/5 px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[length:var(--t-sm)]">📌</span>
                <h3 className="text-[length:var(--t-xs)] font-semibold uppercase tracking-wider text-slate-400">Key Takeaways</h3>
              </div>
              <ul className="space-y-2">
                {bullets.map((b, i) => (
                  <li key={i} className="flex gap-2.5 text-[length:var(--t-sm)] text-slate-200 leading-relaxed">
                    <span className="text-indigo-400/60 mt-0.5 shrink-0 font-semibold">{i + 1}.</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Structured sections */}
          <Section icon="🌙" title="Overnight" items={overnight} />
          <Section icon="🌅" title="Pre-Market" items={premarket} />
          <Section icon="📅" title="Today's Catalysts" items={catalysts} />
          <Section icon="🛢️" title="Commodities" items={commodities} />
          <Section icon="📍" title="Posture" text={row.posture} />
          <Section icon="👀" title="Watch List" items={watch} />

          {/* Full raw markdown */}
          {row.raw_md && (
            <section className="pt-4 border-t border-white/5">
              <div className="flex items-center gap-2 mb-2.5">
                <span className="text-[length:var(--t-base)]">📄</span>
                <h3 className="text-[length:var(--t-xs)] font-semibold uppercase tracking-wider text-slate-400">Full Brief</h3>
              </div>
              <pre className="text-[length:var(--t-xs)] text-slate-300 leading-relaxed whitespace-pre-wrap font-sans break-words">
                {row.raw_md}
              </pre>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
