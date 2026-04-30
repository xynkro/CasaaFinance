import { useState, useRef, useEffect, type ReactNode } from "react";

interface Tab {
  label: string;
}

/**
 * Horizontal swipeable tab container.
 * Native touch listeners so we can preventDefault once horizontal motion dominates.
 * Uses a `dragging` state (not just a ref) so the CSS transition toggles reliably.
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
  const [dragOffset, setDragOffset] = useState(0);
  const [dragging, setDragging] = useState(false);  // <- drives transition correctly

  const activeRef = useRef(active);
  useEffect(() => { activeRef.current = active; }, [active]);

  useEffect(() => {
    if (persistKey) {
      try { localStorage.setItem(persistKey, String(active)); } catch {}
    }
  }, [active, persistKey]);

  const panelsBoxRef = useRef<HTMLDivElement>(null);
  const touch = useRef({ startX: 0, startY: 0, dragX: 0, committed: false, ignored: false });

  useEffect(() => {
    const el = panelsBoxRef.current;
    if (!el) return;

    const H_COMMIT = 10;

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
        if (Math.abs(dx) < H_COMMIT && Math.abs(dy) < H_COMMIT) return;
        if (Math.abs(dy) >= Math.abs(dx)) {
          touch.current.ignored = true;
          return;
        }
        touch.current.committed = true;
        setDragging(true);
      }

      const idx = activeRef.current;
      let draggedX = dx;
      if (idx === 0 && dx > 0)                 draggedX = dx * 0.25;
      else if (idx === tabs.length - 1 && dx < 0) draggedX = dx * 0.25;

      touch.current.dragX = draggedX;
      setDragOffset(draggedX);
      e.preventDefault();
    };

    const onEnd = () => {
      if (!touch.current.committed) {
        touch.current = { startX: 0, startY: 0, dragX: 0, committed: false, ignored: false };
        setDragOffset(0);
        setDragging(false);
        return;
      }

      const threshold = 52;
      const idx = activeRef.current;
      if (touch.current.dragX < -threshold && idx < tabs.length - 1) {
        setActive(idx + 1);
      } else if (touch.current.dragX > threshold && idx > 0) {
        setActive(idx - 1);
      }

      touch.current = { startX: 0, startY: 0, dragX: 0, committed: false, ignored: false };
      setDragOffset(0);
      setDragging(false);
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove,  { passive: false });
    el.addEventListener("touchend",   onEnd);
    el.addEventListener("touchcancel", onEnd);

    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend",   onEnd);
      el.removeEventListener("touchcancel", onEnd);
    };
  }, [tabs.length]);

  const translatePct = -active * 100;
  const trackStyle: React.CSSProperties = {
    transform: `translateX(calc(${translatePct}% + ${dragOffset}px))`,
    transition: dragging ? "none" : "transform 0.28s cubic-bezier(0.4, 0, 0.2, 1)",
  };

  return (
    <div className="flex flex-col">
      {/* Tab header pills */}
      <div className="flex px-4 pt-2 pb-3 gap-1">
        {tabs.map((t, i) => {
          const isActive = i === active;
          return (
            <button
              key={t.label}
              onClick={() => setActive(i)}
              className="flex-1 py-2 px-3 rounded-xl text-[length:var(--t-xs)] font-semibold transition-all duration-200 relative"
              style={{
                background: isActive ? "rgba(255,255,255,0.09)" : "transparent",
                color: isActive ? "#f1f5f9" : "rgb(100 116 139)",
                border: isActive ? "1px solid rgba(255,255,255,0.12)" : "1px solid transparent",
                boxShadow: isActive
                  ? `inset 0 0 0 0.5px rgba(var(--accent-rgb),0.2), 0 2px 10px rgba(0,0,0,0.25)`
                  : "none",
              }}
            >
              {t.label}
              {isActive && (
                <span
                  className="absolute bottom-[3px] left-1/2 -translate-x-1/2 w-3 h-[2px] rounded-full"
                  style={{ background: `rgba(var(--accent-rgb), 0.8)` }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Swipeable panels */}
      <div ref={panelsBoxRef} className="overflow-hidden">
        <div className="swipe-track" style={trackStyle}>
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
