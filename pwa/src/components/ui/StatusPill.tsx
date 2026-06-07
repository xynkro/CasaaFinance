import { resolveStatus } from "./statusConfig";

/**
 * StatusPill — the rounded-full "icon + label" pill that shows a decision's
 * lifecycle state (Pending / Watching / Filled / Killed / Expired).
 *
 * Both DecisionsPage and ClosedDecisionsCard carried their own copy of the
 * STATUS config object AND their own pill markup. This consolidates both:
 * the shared `DECISION_STATUS` map lives in ./statusConfig, and the pill
 * renders from it. (The map + `resolveStatus` live in their own module so this
 * file exports only a component — satisfies react-refresh/only-export-components.)
 *
 * @example
 * <StatusPill status={decision.status} />
 * <StatusPill status="filled" size="sm" />   // compact list-row variant
 *
 * Props / best-practice notes:
 * - `status` is matched case-insensitively against DECISION_STATUS; unknown
 *   values fall back to "pending" (the original DEFAULT_STATUS behavior).
 * - `size`: "md" (default — the detail-card pill, 12px icon/text) or
 *   "sm" (the dense list-row pill, 10px). These match the two existing sizes
 *   exactly so migrated rows look identical.
 * - Accessibility: the icon is decorative (aria-hidden); the human-readable
 *   label text carries the state. The pill is a <span> (not interactive).
 * - Theming: uses the existing Tailwind status tokens (emerald/red/amber/blue/
 *   slate at /10 + /20). No new colors.
 */

export interface StatusPillProps {
  /** Raw decision status (case-insensitive). */
  status: string | undefined | null;
  /** "md" = detail card pill (default), "sm" = dense list-row pill. */
  size?: "md" | "sm";
  className?: string;
}

export function StatusPill({ status, size = "md", className = "" }: StatusPillProps) {
  const cfg = resolveStatus(status);
  const Icon = cfg.icon;
  const md = size === "md";
  return (
    <div
      className={`flex items-center ${md ? "gap-1.5 px-2.5 py-1" : "gap-1 px-2 py-0.5"} rounded-full ${cfg.bg} ${className}`}
    >
      <Icon size={md ? 12 : 10} className={cfg.text} aria-hidden="true" />
      <span
        className={`${md ? "text-[length:var(--t-xs)]" : "text-[length:var(--t-2xs)]"} font-semibold ${cfg.text}`}
      >
        {cfg.label}
      </span>
    </div>
  );
}
