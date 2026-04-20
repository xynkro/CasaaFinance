import { useRef, useState, useEffect, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

const THRESHOLD = 80;   // px pull distance to trigger
const MAX_PULL = 140;   // cap max pull distance
const DAMP = 0.45;      // rubber-band dampening factor

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
  const pulling = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onTouchStart = (e: TouchEvent) => {
      if (refreshing) return;
      // Only start tracking if we're at the top of scroll
      if (el.scrollTop > 2) return;
      startY.current = e.touches[0].clientY;
      pulling.current = false;
    };

    const onTouchMove = (e: TouchEvent) => {
      if (refreshing) return;
      if (startY.current === null) return;
      const dy = e.touches[0].clientY - startY.current;
      if (dy <= 0) {
        pulling.current = false;
        setPullDist(0);
        return;
      }
      if (el.scrollTop > 2) {
        // User scrolled back up during pull; abandon
        pulling.current = false;
        setPullDist(0);
        return;
      }
      // Rubber-band damping: harder to pull further
      const damped = Math.min(MAX_PULL, dy * DAMP);
      setPullDist(damped);
      pulling.current = true;
      // Prevent native overscroll bounce so our indicator is the only feedback
      if (dy > 6) e.preventDefault();
    };

    const onTouchEnd = async () => {
      if (!pulling.current) {
        setPullDist(0);
        startY.current = null;
        return;
      }
      const shouldRefresh = pullDist >= THRESHOLD;
      startY.current = null;
      pulling.current = false;

      if (shouldRefresh) {
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

  // Progress 0→1 for visual feedback
  const progress = Math.min(1, pullDist / THRESHOLD);
  const rotation = pullDist * 3; // rotate while pulling
  const scale = 0.6 + 0.4 * progress;
  const opacity = Math.min(1, progress * 1.5);

  return (
    <div className="ptr-container relative w-full h-full">
      {/* Indicator */}
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

      {/* Content — nudge down when pulling for tactile feel */}
      <div
        style={{
          transform: `translateY(${pullDist * 0.5}px)`,
          transition: pulling.current || refreshing ? "none" : "transform 0.3s cubic-bezier(0.2,0.8,0.2,1)",
          height: "100%",
          width: "100%",
        }}
      >
        {children}
      </div>
    </div>
  );
}
