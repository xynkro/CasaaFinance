import { useState, useRef, useEffect, type ReactNode } from "react";

interface Tab {
  label: string;
  accent?: string;  // Tailwind color class prefix (e.g. "emerald", "blue")
}

export function SwipeTabs({
  tabs,
  panels,
  defaultIndex = 0,
}: {
  tabs: Tab[];
  panels: ReactNode[];
  defaultIndex?: number;
}) {
  const [active, setActive] = useState(defaultIndex);
  const trackRef = useRef<HTMLDivElement>(null);
  const touch = useRef<{ startX: number; startY: number; dragX: number; swiping: boolean }>({
    startX: 0, startY: 0, dragX: 0, swiping: false,
  });
  const [dragOffset, setDragOffset] = useState(0);

  const onTouchStart = (e: React.TouchEvent) => {
    touch.current = {
      startX: e.touches[0].clientX,
      startY: e.touches[0].clientY,
      dragX: 0,
      swiping: false,
    };
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touch.current.startX;
    const dy = e.touches[0].clientY - touch.current.startY;
    // Only register as swipe if horizontal dominant AND we haven't committed to vertical
    if (!touch.current.swiping) {
      if (Math.abs(dx) < 12) return;
      if (Math.abs(dy) > Math.abs(dx)) return;  // scroll wins
      touch.current.swiping = true;
    }
    // Limit drag at boundaries
    if (active === 0 && dx > 0) {
      touch.current.dragX = dx * 0.3;  // rubber-band at first panel
    } else if (active === tabs.length - 1 && dx < 0) {
      touch.current.dragX = dx * 0.3;
    } else {
      touch.current.dragX = dx;
    }
    setDragOffset(touch.current.dragX);
  };

  const onTouchEnd = () => {
    if (!touch.current.swiping) {
      setDragOffset(0);
      return;
    }
    const threshold = 60;
    if (touch.current.dragX < -threshold && active < tabs.length - 1) {
      setActive(active + 1);
    } else if (touch.current.dragX > threshold && active > 0) {
      setActive(active - 1);
    }
    touch.current.dragX = 0;
    touch.current.swiping = false;
    setDragOffset(0);
  };

  // Reset drag when active changes (avoid flicker)
  useEffect(() => {
    setDragOffset(0);
  }, [active]);

  const translatePct = -active * 100;
  const trackStyle: React.CSSProperties = {
    transform: `translateX(calc(${translatePct}% + ${dragOffset}px))`,
    transition: touch.current.swiping ? "none" : "transform 0.3s cubic-bezier(0.2,0.8,0.2,1)",
  };

  return (
    <div className="flex flex-col">
      {/* Tab headers */}
      <div className="flex gap-1 px-4 pt-2 pb-3 relative">
        {tabs.map((t, i) => {
          const isActive = i === active;
          return (
            <button
              key={t.label}
              onClick={() => setActive(i)}
              className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold transition-all ${
                isActive
                  ? "bg-white/10 text-white border border-white/15"
                  : "text-slate-400 hover:text-slate-200 border border-transparent"
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Swipeable panels */}
      <div
        className="overflow-hidden"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
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
