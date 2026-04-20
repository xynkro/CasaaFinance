import { useState, useRef, useEffect, type ReactNode } from "react";

interface Tab {
  label: string;
}

/**
 * Horizontal swipeable tab container. Uses native touch listeners so we can
 * preventDefault once horizontal motion dominates (blocks vertical scroll
 * and parent pull-to-refresh during a commit).
 */
export function SwipeTabs({
  tabs,
  panels,
  defaultIndex = 0,
  persistKey,
}: {
  tabs: Tab[];
  panels: ReactNode[];
  defaultIndex?: number;
  persistKey?: string;
}) {
  // Persisted active index
  const loadInitial = (): number => {
    if (persistKey) {
      try {
        const v = localStorage.getItem(persistKey);
        if (v !== null) {
          const n = Number(v);
          if (Number.isFinite(n) && n >= 0 && n < tabs.length) return n;
        }
      } catch {}
    }
    return defaultIndex;
  };
  const [active, setActive] = useState(loadInitial);

  useEffect(() => {
    if (persistKey) {
      try { localStorage.setItem(persistKey, String(active)); } catch {}
    }
  }, [active, persistKey]);

  const trackRef = useRef<HTMLDivElement>(null);
  const panelsBoxRef = useRef<HTMLDivElement>(null);
  const touch = useRef<{ startX: number; startY: number; dragX: number; committed: boolean; ignored: boolean }>({
    startX: 0, startY: 0, dragX: 0, committed: false, ignored: false,
  });
  const [dragOffset, setDragOffset] = useState(0);
  const activeRef = useRef(active);
  useEffect(() => { activeRef.current = active; }, [active]);

  // Native touch listeners — required to call preventDefault in touchmove.
  useEffect(() => {
    const el = panelsBoxRef.current;
    if (!el) return;

    const H_COMMIT = 12;  // px horizontal motion before committing to swipe

    const onStart = (e: TouchEvent) => {
      touch.current = {
        startX: e.touches[0].clientX,
        startY: e.touches[0].clientY,
        dragX: 0,
        committed: false,
        ignored: false,
      };
    };

    const onMove = (e: TouchEvent) => {
      if (touch.current.ignored) return;
      const dx = e.touches[0].clientX - touch.current.startX;
      const dy = e.touches[0].clientY - touch.current.startY;

      if (!touch.current.committed) {
        // Need horizontal dominance to commit
        if (Math.abs(dx) < H_COMMIT && Math.abs(dy) < H_COMMIT) return;
        if (Math.abs(dy) > Math.abs(dx)) {
          // Vertical wins — disqualify this touch so we don't fight native scroll
          touch.current.ignored = true;
          return;
        }
        touch.current.committed = true;
      }

      // Rubber-band at edges
      const idx = activeRef.current;
      let draggedX = dx;
      if (idx === 0 && dx > 0) draggedX = dx * 0.3;
      else if (idx === tabs.length - 1 && dx < 0) draggedX = dx * 0.3;

      touch.current.dragX = draggedX;
      setDragOffset(draggedX);
      // Committed to horizontal — block vertical scroll
      e.preventDefault();
    };

    const onEnd = () => {
      if (touch.current.ignored || !touch.current.committed) {
        touch.current.ignored = false;
        touch.current.committed = false;
        setDragOffset(0);
        return;
      }
      const threshold = 60;
      const idx = activeRef.current;
      if (touch.current.dragX < -threshold && idx < tabs.length - 1) {
        setActive(idx + 1);
      } else if (touch.current.dragX > threshold && idx > 0) {
        setActive(idx - 1);
      }
      touch.current.dragX = 0;
      touch.current.committed = false;
      touch.current.ignored = false;
      setDragOffset(0);
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", onEnd);

    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
    };
  }, [tabs.length]);

  const translatePct = -active * 100;
  const trackStyle: React.CSSProperties = {
    transform: `translateX(calc(${translatePct}% + ${dragOffset}px))`,
    transition: touch.current.committed ? "none" : "transform 0.3s cubic-bezier(0.2,0.8,0.2,1)",
  };

  return (
    <div className="flex flex-col">
      {/* Tab headers */}
      <div className="flex gap-1 px-4 pt-2 pb-3">
        {tabs.map((t, i) => {
          const isActive = i === active;
          return (
            <button
              key={t.label}
              onClick={() => setActive(i)}
              className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold transition-all ${
                isActive
                  ? "bg-white/12 text-white border border-white/15 shadow-sm"
                  : "text-slate-400 hover:text-slate-200 border border-transparent"
              }`}
              style={isActive ? {
                boxShadow: `inset 0 0 0 1px rgba(var(--accent-rgb), 0.22), 0 4px 12px rgba(var(--accent-rgb), 0.12)`,
              } : undefined}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Swipeable panels — native listeners attached via useEffect */}
      <div ref={panelsBoxRef} className="overflow-hidden">
        <div ref={trackRef} className="swipe-track" style={trackStyle}>
          {panels.map((panel, i) => (
            <div key={i} className="swipe-panel">
              {panel}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
