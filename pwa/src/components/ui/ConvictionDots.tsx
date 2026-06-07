/**
 * ConvictionDots — a 1–5 filled-dot conviction meter.
 *
 * Renders a fixed row of `max` dots; the first `level` are filled (indigo),
 * the rest dimmed (slate). This was copy-pasted verbatim into DecisionsPage,
 * ClosedDecisionsCard, and conceptually mirrored in the harvest/plan cards —
 * this is the single source of truth.
 *
 * @example
 * <ConvictionDots level={4} />            // 4 of 5 filled
 * <ConvictionDots level={2} max={3} />    // 2 of 3 filled
 *
 * Props / best-practice notes:
 * - `level` is clamped to [0, max]; out-of-range brain data won't overflow.
 * - Theming uses the app's indigo "conviction" accent (bg-indigo-400) +
 *   the standard dimmed track (bg-slate-700). No new colors introduced.
 * - Accessibility: the dot row is decorative, so the component exposes a
 *   single semantic value via role="img" + aria-label ("Conviction 4 of 5"),
 *   and the individual dots are aria-hidden. Screen readers hear one number,
 *   not five anonymous bullets.
 * - Responsive: dots are 6px (w-1.5) with 2px gaps — unchanged at phone width.
 */
export interface ConvictionDotsProps {
  /** Number of filled dots (the conviction score). Clamped to [0, max]. */
  level: number;
  /** Total dots to render. Defaults to 5. */
  max?: number;
  /** Optional extra classes on the wrapper. */
  className?: string;
}

export function ConvictionDots({ level, max = 5, className = "" }: ConvictionDotsProps) {
  const filled = Math.max(0, Math.min(max, Math.round(level)));
  return (
    <div
      role="img"
      aria-label={`Conviction ${filled} of ${max}`}
      className={`flex gap-0.5 ${className}`}
    >
      {Array.from({ length: max }).map((_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className={`w-1.5 h-1.5 rounded-full ${i < filled ? "bg-indigo-400" : "bg-slate-700"}`}
        />
      ))}
    </div>
  );
}
