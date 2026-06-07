import type { ComponentType } from "react";
import {
  Clock,
  Target,
  CheckCircle,
  XCircle,
  AlertTriangle,
  type LucideProps,
} from "lucide-react";

/**
 * StatusPill — the rounded-full "icon + label" pill that shows a decision's
 * lifecycle state (Pending / Watching / Filled / Killed / Expired).
 *
 * Both DecisionsPage and ClosedDecisionsCard carried their own copy of the
 * STATUS config object AND their own pill markup. This consolidates both:
 * the shared `DECISION_STATUS` map lives here, and the pill renders from it.
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

export interface DecisionStatusConfig {
  icon: ComponentType<LucideProps>;
  /** Tailwind background utility (e.g. "bg-emerald-500/10"). */
  bg: string;
  /** Tailwind text-color utility (e.g. "text-emerald-400"). */
  text: string;
  /** Tailwind border utility (e.g. "border-emerald-500/20"). */
  border: string;
  /** Human-readable label. */
  label: string;
}

/** Canonical decision-status style map — single source of truth. */
export const DECISION_STATUS: Record<string, DecisionStatusConfig> = {
  pending:  { icon: Clock,         bg: "bg-amber-500/10",   text: "text-amber-400",   border: "border-amber-500/20",   label: "Pending" },
  watching: { icon: Target,        bg: "bg-blue-500/10",    text: "text-blue-400",    border: "border-blue-500/20",    label: "Watching" },
  filled:   { icon: CheckCircle,   bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/20", label: "Filled" },
  killed:   { icon: XCircle,       bg: "bg-red-500/10",     text: "text-red-400",     border: "border-red-500/20",     label: "Killed" },
  expired:  { icon: AlertTriangle, bg: "bg-slate-500/10",   text: "text-slate-400",   border: "border-slate-500/20",   label: "Expired" },
};

/** Resolve a (possibly messy) status string to its config, defaulting to pending. */
export function resolveStatus(status: string | undefined | null): DecisionStatusConfig {
  return DECISION_STATUS[(status || "").toLowerCase()] ?? DECISION_STATUS.pending;
}

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
