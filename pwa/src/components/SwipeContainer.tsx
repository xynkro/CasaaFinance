import type { ReactNode } from "react";

interface Props {
  activeIndex: number;
  children: ReactNode[];
}

/** Simple tab container — no swipe, just shows the active page. */
export function SwipeContainer({ activeIndex, children }: Props) {
  return (
    <div className="h-full overflow-y-auto overflow-x-hidden -webkit-overflow-scrolling-touch">
      {children[activeIndex]}
    </div>
  );
}
