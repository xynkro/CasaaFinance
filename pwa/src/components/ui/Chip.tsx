import type { ReactNode, CSSProperties } from "react";

/**
 * Chip — the small pill/badge used everywhere to surface a single labelled
 * data point (moneyness, conviction score, status, bucket, sector, etc).
 *
 * This is the one primitive behind the `px-1.5/2 py-0.5 rounded text-2xs
 * font-bold border` pattern that was inlined across 15+ cards. Two coloring
 * modes are supported so it can absorb both existing conventions:
 *
 *   1. Tailwind tokens  →  pass `className` with bg/text/border utilities
 *      <Chip className="bg-emerald-500/15 text-emerald-400 border-emerald-500/20">OTM</Chip>
 *
 *   2. Dynamic hex color →  pass `color`; the chip derives a tinted bg + border
 *      <Chip color="#34d399">STRONG BUY</Chip>   // bg = #34d3911a, border = #34d33933
 *
 * @example
 * <Chip icon={<Calendar size={10} />} color="#fcd34d" title="Earnings 2026-06-12">ER 06-12</Chip>
 *
 * Props / best-practice notes:
 * - Keep contents to ONE line + ONE icon + ONE data point (the project's
 *   InfoChips design rule). Don't nest chips.
 * - `size`: "xs" (10px, default — the dominant secondary tier) or "sm" (12px).
 * - `pad`: horizontal padding — "sm" (px-1.5, default) or "md" (px-2).
 * - `tone`: "bold" (font-bold), "semibold", or "medium" (default) weight.
 * - Accessibility: renders a <span>; if `title` is set it also becomes the
 *   accessible label so hover tooltips are exposed to AT. Icons inside should
 *   be decorative (the label carries the meaning).
 * - Theming: when `color` is omitted, the chip is fully driven by `className`
 *   so it inherits whatever existing tokens the call site used — zero visual
 *   drift on migration.
 */
export interface ChipProps {
  children: ReactNode;
  /** Optional leading icon (decorative — keep it ~10px). */
  icon?: ReactNode;
  /** Dynamic hex/rgb color → auto-tinted background + border + text. */
  color?: string;
  /** Native title (tooltip); also used as aria-label when provided. */
  title?: string;
  /** Type scale: "xs" = --t-2xs (10px, default), "sm" = --t-xs (12px). */
  size?: "xs" | "sm";
  /** Horizontal padding: "sm" = px-1.5 (default), "md" = px-2. */
  pad?: "sm" | "md";
  /** Font weight emphasis. */
  tone?: "bold" | "semibold" | "medium";
  /** Render numbers with tabular-nums (recommended for figures/dates). */
  tabular?: boolean;
  /** Extra classes (use for Tailwind-token coloring when `color` is unset). */
  className?: string;
  /** Inline style overrides (merged after the color-derived styles). */
  style?: CSSProperties;
}

export function Chip({
  children,
  icon,
  color,
  title,
  size = "xs",
  pad = "sm",
  tone = "medium",
  tabular = false,
  className = "",
  style,
}: ChipProps) {
  const sizeClass = size === "sm" ? "text-[length:var(--t-xs)]" : "text-[length:var(--t-2xs)]";
  const padClass = pad === "md" ? "px-2" : "px-1.5";
  const weightClass =
    tone === "bold" ? "font-bold" : tone === "semibold" ? "font-semibold" : "font-medium";
  const colorStyle: CSSProperties | undefined = color
    ? { background: `${color}1a`, border: `1px solid ${color}33`, color }
    : undefined;

  return (
    <span
      title={title}
      aria-label={title}
      className={`inline-flex items-center gap-1 ${padClass} py-0.5 rounded ${sizeClass} ${weightClass} ${
        tabular ? "tabular-nums" : ""
      } ${className}`}
      style={{ ...colorStyle, ...style }}
    >
      {icon}
      {children}
    </span>
  );
}
