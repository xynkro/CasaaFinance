import type {
  EarningsRow,
  AnalystConsensusRow,
  NewsSummary,
  InsiderSummary,
  TriggerEvaluation,
} from "../data";
import { Calendar, ArrowDownRight, ArrowUpRight, Megaphone, Users, Zap, Hourglass } from "lucide-react";
import { Chip } from "../components/ui";

/**
 * Phase 6 — small chips that surface Finnhub-derived context on
 * Decision cards. Each component is null-safe (returns null when no
 * data) so cards stay clean when the brain has nothing to show.
 *
 * Design principle: every chip is ONE line, ONE emoji-icon, ONE
 * data point. No nested badges, no double-coloring. The brain's
 * thesis_1liner stays the focal text — chips are silent context.
 */

// --- Earnings badge ---------------------------------------------------------

/**
 * Earnings badge — shows when ticker has earnings within `windowDays`.
 * Color escalates as the date approaches: amber within 14d, red within 5d.
 */
export function EarningsBadge({
  earnings,
  windowDays = 14,
}: {
  earnings?: EarningsRow;
  windowDays?: number;
}) {
  if (!earnings || !earnings.date) return null;
  const today = new Date().toISOString().slice(0, 10);
  const daysUntil = Math.round(
    (new Date(earnings.date).getTime() - new Date(today).getTime()) / 86400000,
  );
  if (daysUntil < 0 || daysUntil > windowDays) return null;
  const urgent = daysUntil <= 5;
  const bg = urgent ? "rgba(239,68,68,0.12)" : "rgba(251,191,36,0.10)";
  const border = urgent ? "rgba(239,68,68,0.25)" : "rgba(251,191,36,0.20)";
  const color = urgent ? "#fca5a5" : "#fcd34d";
  const hourLabel = earnings.hour === "bmo" ? "BMO"
    : earnings.hour === "amc" ? "AMC"
    : earnings.hour === "dmh" ? "DMH" : "";
  return (
    <Chip
      title={`Earnings ${earnings.date} ${hourLabel}${earnings.eps_estimate ? ` · est $${earnings.eps_estimate}` : ""}`}
      icon={<Calendar size={10} />}
      tone="semibold"
      tabular
      style={{ background: bg, border: `1px solid ${border}`, color }}
    >
      ER {earnings.date.slice(5)}{hourLabel ? ` ${hourLabel}` : ""}
    </Chip>
  );
}

// --- Analyst chip -----------------------------------------------------------

const ANALYST_COLOR: Record<string, string> = {
  STRONG_BUY: "#34d399",
  BUY: "#86efac",
  HOLD: "#94a3b8",
  SELL: "#fca5a5",
  STRONG_SELL: "#ef4444",
};

export function AnalystChip({ analyst }: { analyst?: AnalystConsensusRow }) {
  if (!analyst) return null;
  const total = Number(analyst.total_count) || 0;
  if (total < 3) return null; // skip thinly-covered names
  const label = analyst.consensus_label || "HOLD";
  const color = ANALYST_COLOR[label] ?? "#94a3b8";
  const sb = Number(analyst.strong_buy_count) || 0;
  const b = Number(analyst.buy_count) || 0;
  const h = Number(analyst.hold_count) || 0;
  const s = Number(analyst.sell_count) || 0;
  const ss = Number(analyst.strong_sell_count) || 0;
  return (
    <Chip
      title={`Wall St: ${sb} SB / ${b} B / ${h} H / ${s} S / ${ss} SS  (${total} analysts, ${label})`}
      icon={<Users size={10} />}
      color={color}
      tabular
    >
      {label.replace("_", " ")}
    </Chip>
  );
}

// --- News sentiment dot -----------------------------------------------------

export function NewsSentimentDot({ news }: { news?: NewsSummary }) {
  if (!news || news.count_72h === 0) return null;
  const score = news.worst_score < -Math.abs(news.best_score) ? news.worst_score : news.best_score;
  let color: string;
  let label: string;
  if (score >= 0.4) { color = "#34d399"; label = "Positive news"; }
  else if (score <= -0.4) { color = "#f87171"; label = "Negative news"; }
  else if (score <= -0.15 || score >= 0.15) { color = "#fbbf24"; label = "Mixed news"; }
  else return null; // neutral & low signal — don't add visual noise
  return (
    <Chip
      title={`${label} (worst ${news.worst_score.toFixed(2)} / best ${news.best_score.toFixed(2)} over 72h, ${news.count_72h} articles): "${news.latest_headline.slice(0, 100)}"`}
      icon={<Megaphone size={10} />}
      style={{ background: `${color}18`, border: `1px solid ${color}33`, color }}
    >
      {label.replace(" news", "")}
    </Chip>
  );
}

// --- Trigger state badge ----------------------------------------------------

/**
 * Trigger state badge — bridges the gap between Watching and Filled.
 *
 * The brain writes a `watching` row and may not re-emit for 2-3 days.
 * This badge evaluates the trigger CLIENT-SIDE (`evaluateTrigger()` in
 * data.ts) using live prices + regime + TV signals, so the user sees
 * "ACT NOW" the moment the conditions clear — without waiting for the
 * next WSR run.
 *
 *   close   → amber Hourglass — within 3% of trigger
 *   ready   → blue Hourglass — trigger hit, gate (regime / TV) blocks
 *   act_now → red pulsing Zap — trigger hit, all gates clear
 *   dormant → null (no chip when nothing is happening)
 */
export function TriggerBadge({ evaluation }: { evaluation: TriggerEvaluation }) {
  if (evaluation.state === "dormant") return null;

  const cfg = {
    act_now: {
      bg: "rgba(239,68,68,0.15)",
      border: "rgba(239,68,68,0.45)",
      color: "#fca5a5",
      label: "ACT NOW",
      Icon: Zap,
      pulse: true,
    },
    ready: {
      bg: "rgba(96,165,250,0.12)",
      border: "rgba(96,165,250,0.30)",
      color: "#93c5fd",
      label: "Ready (gated)",
      Icon: Hourglass,
      pulse: false,
    },
    close: {
      bg: "rgba(251,191,36,0.10)",
      border: "rgba(251,191,36,0.25)",
      color: "#fcd34d",
      label: "Close",
      Icon: Hourglass,
      pulse: false,
    },
  }[evaluation.state];

  const Icon = cfg.Icon;
  return (
    <span
      title={evaluation.reason}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold uppercase tracking-wide${
        cfg.pulse ? " animate-pulse" : ""
      }`}
      style={{
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        color: cfg.color,
      }}
    >
      <Icon size={11} />
      {cfg.label}
    </span>
  );
}

// --- Insider flow icon ------------------------------------------------------

export function InsiderFlowIcon({ insider }: { insider?: InsiderSummary }) {
  if (!insider) return null;
  // Only surface when net flow is meaningful: |net buy| > $250k.
  if (Math.abs(insider.net_buy_value) < 250_000) return null;
  const isBuy = insider.net_buy_value > 0;
  const color = isBuy ? "#34d399" : "#fbbf24";
  const Icon = isBuy ? ArrowUpRight : ArrowDownRight;
  const millions = (Math.abs(insider.net_buy_value) / 1_000_000).toFixed(1);
  return (
    <Chip
      title={`Insider net ${isBuy ? "buy" : "sell"} $${(Math.abs(insider.net_buy_value) / 1000).toFixed(0)}k last 7d (largest: ${insider.largest_name} $${(insider.largest_value / 1000).toFixed(0)}k)`}
      icon={<Icon size={10} />}
      tabular
      style={{ background: `${color}18`, border: `1px solid ${color}33`, color }}
    >
      {isBuy ? "Insider buy" : "Insider sell"} ${millions}M
    </Chip>
  );
}
