/**
 * DeltaText — a signed numeric value colored green when ≥ 0 and red when < 0.
 *
 * The `value >= 0 ? "text-emerald-400" : "text-red-400"` ternary (with
 * tabular-nums) was repeated across PaperTradingView, HarvestPage,
 * ActiveHarvestCard, WheelCard and many P&L surfaces. This centralizes the
 * sign→color mapping and the figure formatting.
 *
 * @example
 * <DeltaText value={upl} format="money" />           // "+$1,240.50" green
 * <DeltaText value={changePct} format="percent" />   // "-3.2%" red
 * <DeltaText value={42} suffix=" bps" />              // "+42 bps"
 *
 * Props / best-practice notes:
 * - This component owns ONLY the at-zero sign coloring. Threshold-based
 *   coloring (e.g. red ≥ 30, green ≤ -30, ITM/OTM semantics) is intentionally
 *   NOT folded in here — those are context-specific and stay at the call site.
 * - `format`: "money" ($, 2dp, grouped), "percent" (1dp + %), or "raw"
 *   (uses `digits`). All render with a leading "+" on non-negative values
 *   unless `showPlus={false}`.
 * - `tabular` defaults true so columns of figures align (tabular-nums).
 * - Accessibility: renders a <span>; the sign is in the visible text so AT
 *   reads the direction. Color is never the sole signal.
 * - Theming: emerald-400 / red-400 — the app's standard gain/loss tokens.
 */
export interface DeltaTextProps {
  /** The signed value. */
  value: number;
  /** Output format. Defaults to "raw". */
  format?: "money" | "percent" | "raw";
  /** Decimal places for "raw" / overrides default for money/percent. */
  digits?: number;
  /** Show a leading "+" for values ≥ 0. Defaults true. */
  showPlus?: boolean;
  /** Trailing unit (e.g. " bps", "%"). Ignored for money/percent presets. */
  suffix?: string;
  /** Use tabular-nums. Defaults true. */
  tabular?: boolean;
  className?: string;
}

export function DeltaText({
  value,
  format = "raw",
  digits,
  showPlus = true,
  suffix = "",
  tabular = true,
  className = "",
}: DeltaTextProps) {
  const positive = value >= 0;
  const sign = positive && showPlus ? "+" : "";
  const abs = Math.abs(value);

  let body: string;
  if (format === "money") {
    const d = digits ?? 2;
    body = `${value < 0 ? "-" : ""}$${abs.toLocaleString("en-US", {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    })}`;
    body = positive ? `${sign}${body}` : body;
  } else if (format === "percent") {
    const d = digits ?? 1;
    body = `${sign}${value.toFixed(d)}%`;
  } else {
    const d = digits ?? 0;
    body = `${sign}${value.toFixed(d)}${suffix}`;
  }

  return (
    <span
      className={`${tabular ? "tabular-nums " : ""}${positive ? "text-emerald-400" : "text-red-400"} ${className}`}
    >
      {body}
    </span>
  );
}
