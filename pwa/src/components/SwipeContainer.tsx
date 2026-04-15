import { useRef, useState, type ReactNode } from "react";

interface Props {
  activeIndex: number;
  onChangeIndex: (i: number) => void;
  children: ReactNode[];
}

export function SwipeContainer({ activeIndex, onChangeIndex, children }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const touchRef = useRef({ startX: 0, startY: 0, moving: false });
  const [offset, setOffset] = useState(0);
  const count = children.length;

  const onTouchStart = (e: React.TouchEvent) => {
    touchRef.current = {
      startX: e.touches[0].clientX,
      startY: e.touches[0].clientY,
      moving: false,
    };
    setOffset(0);
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchRef.current.startX;
    const dy = e.touches[0].clientY - touchRef.current.startY;

    // Only hijack horizontal swipes
    if (!touchRef.current.moving) {
      if (Math.abs(dy) > Math.abs(dx)) return; // vertical scroll
      if (Math.abs(dx) > 10) touchRef.current.moving = true;
    }

    if (touchRef.current.moving) {
      // Resist at edges
      const atLeft = activeIndex === 0 && dx > 0;
      const atRight = activeIndex === count - 1 && dx < 0;
      const dampened = atLeft || atRight ? dx * 0.2 : dx;
      setOffset(dampened);
    }
  };

  const onTouchEnd = () => {
    if (!touchRef.current.moving) {
      setOffset(0);
      return;
    }
    const threshold = 60;
    if (offset < -threshold && activeIndex < count - 1) {
      onChangeIndex(activeIndex + 1);
    } else if (offset > threshold && activeIndex > 0) {
      onChangeIndex(activeIndex - 1);
    }
    setOffset(0);
  };

  return (
    <div
      ref={containerRef}
      className="overflow-hidden"
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      <div
        className="flex transition-transform duration-300 ease-out"
        style={{
          transform: `translateX(calc(-${activeIndex * 100}% + ${offset}px))`,
          transitionDuration: offset !== 0 ? "0ms" : "300ms",
        }}
      >
        {children.map((child, i) => (
          <div key={i} className="w-full shrink-0">
            {child}
          </div>
        ))}
      </div>
    </div>
  );
}
