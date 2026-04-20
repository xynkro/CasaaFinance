import { useRef, useState, useEffect, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

const THRESHOLD = 80;      // px pull distance to trigger
const MAX_PULL = 140;      // cap max pull distance
const DAMP = 0.45;         // rubber-band dampening factor
const H_IGNORE = 10;       // px of horizontal motion that disqualifies the pull
const V_MIN_TO_START = 8;  // px of vertical motion before we treat as a pull

export function PullToRefresh({
  children,
  onRefresh,
  scrollRef,
}: {
  children: ReactNode;
  onRefresh: () => Promise<void> | void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
}) {
  const [pullDist, setPullDist] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const startY = useRef<number | null>(null);
  const startX = useRef<number | null>(null);
  const pulling = useRef(false);
  const disqualified = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onTouchStart = (e: TouchEvent) => {
      if (refreshing) return;
      if (el.scrollTop > 2) return;
      startY.current = e.touches[0].clientY;
      startX.current = e.touches[0].clientX;
      pulling.current = false;
      disqualified.current = false;
    };

    const onTouchMove = (e: TouchEvent) => {
      if (refreshing) return;
      if (startY.current === null || startX.current === null) return;
      if (disqualified.current) return;

      const dy = e.touches[0].clientY - startY.current;
      const dx = e.touches[0].clientX - startX.current;

      // Horizontal gesture → disqualify this pull attempt for the rest of the
      // touch so children (SwipeTabs) can handle it without interference.
      if (Math.abs(dx) > H_IGNORE && Math.abs(dx) > Math.abs(dy)) {
        disqualified.current = true;
        pulling.current = false;
        setPullDist(0);
        return;
      }

      // Not enough vertical motion yet — don't start pull UI
      if (dy < V_MIN_TO_START) {
        pulling.current = false;
        setPullDist(0);
        return;
      }

      if (el.scrollTop > 2) {
        pulling.current = false;
        setPullDist(0);
        return;
      }

      const damped = Math.min(MAX_PULL, dy * DAMP);
      setPullDist(damped);
      pulling.current = true;
      if (dy > V_MIN_TO_START) e.preventDefault();
    };

    const onTouchEnd = async () => {
      const wasPulling = pulling.current;
      const currentPull = pullDist;
      startY.current = null;
      startX.current = null;
      pulling.current = false;
      disqualified.current = false;

      if (!wasPulling) {
        setPullDist(0);
        return;
      }

      if (currentPull >= THRESHOLD) {
        setRefreshing(true);
        setPullDist(THRESHOLD);
        try {
          await onRefresh();
        } finally {
          setRefreshing(false);
          setPullDist(0);
        }
      } else {
        setPullDist(0);
      }
    };

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", onTouchEnd);
    el.addEventListener("touchcancel", onTouchEnd);

    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [scrollRef, refreshing, pullDist, onRefresh]);

  const progress = Math.min(1, pullDist / THRESHOLD);
  const rotation = pullDist * 3;
  const scale = 0.6 + 0.4 * progress;
  const opacity = Math.min(1, progress * 1.5);

  // Always render the SAME single wrapper div so React doesn't remount the
  // children subtree on pull start/end (that was resetting sub-tab state).
  // Use transform:none when idle so no new containing block is created —
  // this preserves position:sticky on descendants.
  const isActive = pullDist > 0 || refreshing;
  const wrapperStyle: React.CSSProperties = {
    width: "100%",
    height: "100%",
    transform: isActive ? `translateY(${pullDist * 0.5}px)` : "none",
    transition: pulling.current || refreshing ? "none" : "transform 0.3s cubic-bezier(0.2,0.8,0.2,1)",
  };

  return (
    <div className="ptr-container relative w-full h-full">
      <div
        className="ptr-indicator"
        style={{
          top: `${Math.max(10, pullDist - 20)}px`,
          transform: `translateX(-50%) scale(${scale})`,
          opacity,
        }}
      >
        <RefreshCw
          size={22}
          className={`text-white ${refreshing ? "spin-smooth" : ""}`}
          style={{ transform: refreshing ? undefined : `rotate(${rotation}deg)` }}
        />
      </div>

      <div style={wrapperStyle}>
        {children}
      </div>
    </div>
  );
}
