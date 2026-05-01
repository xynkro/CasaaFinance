import { Shield, Target, AlertTriangle, TrendingUp, Package, CheckCircle2, Clock } from "lucide-react";

/**
 * Status metadata for exit-plan rows. Lives in /lib because it's shared
 * by both the badge component (ExitPlanPanel.tsx) and the panel itself —
 * mixing a constant export with component exports broke React Fast Refresh.
 */
export const STATUS_META: Record<string, {
  label: string;
  bg: string;
  border: string;
  text: string;
  icon: typeof Shield;
}> = {
  HEALTHY: {
    label: "Healthy",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
    text: "text-emerald-400",
    icon: CheckCircle2,
  },
  WARNING: {
    label: "Warning",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: AlertTriangle,
  },
  STOP_TRIGGERED: {
    label: "Stop Hit",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    text: "text-red-400",
    icon: AlertTriangle,
  },
  T1_HIT: {
    label: "T1 Hit",
    bg: "bg-indigo-500/10",
    border: "border-indigo-500/20",
    text: "text-indigo-400",
    icon: Target,
  },
  T2_HIT: {
    label: "T2 Hit",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
    text: "text-emerald-400",
    icon: TrendingUp,
  },
  BAG: {
    label: "Bag",
    bg: "bg-red-500/15",
    border: "border-red-500/30",
    text: "text-red-400",
    icon: Package,
  },
  TIME_STOP: {
    label: "Time Stop",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: Clock,
  },
  PROFIT_TARGET_HIT: {
    label: "Close Target",
    bg: "bg-emerald-500/15",
    border: "border-emerald-500/30",
    text: "text-emerald-400",
    icon: CheckCircle2,
  },
  ROLL_OR_ASSIGN: {
    label: "Roll/Assign",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: AlertTriangle,
  },
  LET_EXPIRE: {
    label: "Let Expire",
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
    text: "text-slate-400",
    icon: Clock,
  },
  BREACH_WARNING: {
    label: "Breach Risk",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    text: "text-red-400",
    icon: AlertTriangle,
  },
  CATALYST_WARNING: {
    label: "Catalyst",
    bg: "bg-orange-500/10",
    border: "border-orange-500/20",
    text: "text-orange-400",
    icon: AlertTriangle,
  },
  HOLD: {
    label: "Hold",
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
    text: "text-slate-400",
    icon: Shield,
  },
};
