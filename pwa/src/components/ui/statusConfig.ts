/**
 * statusConfig — the canonical decision-status style map + resolver.
 *
 * Lives in its own module (not in StatusPill.tsx) so StatusPill.tsx exports
 * ONLY a component, satisfying `react-refresh/only-export-components`. The map
 * and the `resolveStatus` helper were previously co-located with the component
 * and are re-exported through ui/index.ts, so existing importers are unchanged.
 */
import type { ComponentType } from "react";
import {
  Clock,
  Target,
  CheckCircle,
  XCircle,
  AlertTriangle,
  type LucideProps,
} from "lucide-react";

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
