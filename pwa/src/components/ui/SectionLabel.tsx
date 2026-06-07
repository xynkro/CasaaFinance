import type { ReactNode } from "react";

/**
 * SectionLabel — the small uppercase, letter-spaced caption that heads a
 * sub-section inside a card ("DEPLOYMENT", "TOP MOVERS", "CALIBRATION", …).
 *
 * The exact string `text-[length:var(--t-2xs)] uppercase font-semibold
 * tracking-wider text-slate-500` was inlined dozens of times. This is it.
 *
 * @example
 * <SectionLabel>Accumulation</SectionLabel>
 * <SectionLabel as="h3" icon={<TrendingUp size={11} />} color="#34d399">Gainers</SectionLabel>
 *
 * Props / best-practice notes:
 * - `as`: choose the semantic element. Defaults to a non-heading <div>
 *   (most call sites are visual captions, not document headings). Pass
 *   "h2"/"h3" when the label genuinely starts a heading-level section so
 *   screen-reader users get the outline.
 * - `icon`: optional leading icon (decorative, ~11px).
 * - `color`: override the default slate-500 via inline color (e.g. emerald
 *   for a "gainers" header). Omit to keep the neutral caption tone.
 * - Theming: --t-2xs type scale + slate-500; no new colors.
 */
export interface SectionLabelProps {
  children: ReactNode;
  /** Semantic element. Defaults to "div" (caption, not a heading). */
  as?: "div" | "span" | "h2" | "h3" | "h4";
  /** Optional leading icon (decorative). */
  icon?: ReactNode;
  /** Inline color override (e.g. "#34d399"). Falls back to slate-500. */
  color?: string;
  className?: string;
}

export function SectionLabel({
  children,
  as: Tag = "div",
  icon,
  color,
  className = "",
}: SectionLabelProps) {
  const base =
    "text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider";
  const colorClass = color ? "" : "text-slate-500";
  return (
    <Tag
      className={`${icon ? "flex items-center gap-1.5 " : ""}${base} ${colorClass} ${className}`}
      style={color ? { color } : undefined}
    >
      {icon}
      {children}
    </Tag>
  );
}
