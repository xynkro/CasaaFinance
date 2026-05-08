import { useState } from "react";
import type {
  DecisionRow,
  ExposurePostureRow,
  PositionRow,
  ScreenCandidateRow,
  SnapshotRow,
  TechnicalScoreRow,
  OptionsDefenseRow,
  WheelNextLegRow,
  ExitPlanRow,
  TvConsensus,
  EarningsRow,
  AnalystConsensusRow,
  NewsSummary,
  InsiderSummary,
} from "../data";
import { Card } from "../cards/Card";
import { BuyRecommendationsCard } from "../cards/BuyRecommendationsCard";
import { FreshIdeasCard } from "../cards/FreshIdeasCard";
import { ActionQueueCard } from "../cards/ActionQueueCard";
import { ExposureBudgetCard } from "../cards/ExposureBudgetCard";
import {
  EarningsBadge,
  AnalystChip,
  NewsSentimentDot,
  InsiderFlowIcon,
  TriggerBadge,
} from "../cards/InfoChips";
import { evaluateTrigger } from "../data";
import { DecisionActionRow } from "../cards/DecisionActionRow";
import { StockDetail } from "../components/StockDetail";
import { daysAgo } from "../lib/dates";
import {
  Target,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronRight,
  Copy,
  Check,
  ExternalLink,
  AlertCircle,
} from "lucide-react";

const OPTIONS_STRATEGIES = ["CSP", "CC", "PMCC", "LONG_CALL", "LONG_PUT"];
const SHARE_STRATEGIES = ["BUY_DIP", "TRIM", ""];

function fmtMoney(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * Mantissa-aware money formatter for sub-cent option premiums.
 * Below $0.10 we render 4 decimals so $0.0095 doesn't get rounded to $0.01.
 */
function fmtMoneyMantissa(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  if (n > 0 && n < 0.1) {
    return `$${n.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
  }
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

function fmtExpiry(expiry: string | undefined): string {
  if (!expiry) return "—";
  if (expiry.length === 8 && /^\d+$/.test(expiry)) {
    return `${expiry.slice(4, 6)}/${expiry.slice(6, 8)}`;
  }
  return expiry;
}

const STATUS_CONFIG: Record<string, {
  icon: typeof Target;
  bg: string;
  text: string;
  border: string;
  label: string;
}> = {
  pending: {
    icon: Clock,
    bg: "bg-amber-500/10",
    text: "text-amber-400",
    border: "border-amber-500/20",
    label: "Pending",
  },
  watching: {
    icon: Target,
    bg: "bg-blue-500/10",
    text: "text-blue-400",
    border: "border-blue-500/20",
    label: "Watching",
  },
  filled: {
    icon: CheckCircle,
    bg: "bg-emerald-500/10",
    text: "text-emerald-400",
    border: "border-emerald-500/20",
    label: "Filled",
  },
  killed: {
    icon: XCircle,
    bg: "bg-red-500/10",
    text: "text-red-400",
    border: "border-red-500/20",
    label: "Killed",
  },
  expired: {
    icon: AlertTriangle,
    bg: "bg-slate-500/10",
    text: "text-slate-400",
    border: "border-slate-500/20",
    label: "Expired",
  },
};

const DEFAULT_STATUS = STATUS_CONFIG.pending;

function ConvictionDots({ level }: { level: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${
            i <= level ? "bg-indigo-400" : "bg-slate-700"
          }`}
        />
      ))}
    </div>
  );
}

/**
 * Phased deployment plan row — shows total qty + tranche breakdown for any rec.
 * Works for both share strategies (qty=shares, "5sh now | 5sh +30d") and
 * option strategies (qty=contracts, "1 CSP @ $250P 35DTE now | 1 CSP +14d").
 * Hidden when both qty and accumulation_plan are absent.
 *
 * The plan is pipe-separated; we render each tranche on its own line with
 * a Tn label so the schedule is scannable at a glance.
 *
 * Header label switches between "Accumulation" (shares — building up) and
 * "Deployment" (options — laddering contracts), and the total uses "sh" vs
 * "contracts" so the unit is unambiguous.
 */
function AccumulationPlanRow({ decision }: { decision: DecisionRow }) {
  const planRaw = decision.accumulation_plan?.trim();
  const qty = Number(decision.qty) || 0;
  if (!planRaw && !qty) return null;

  const isOption = OPTIONS_STRATEGIES.includes(decision.strategy ?? "");
  const headerLabel = isOption ? "Deployment" : "Accumulation";
  const unitLabel = isOption ? (qty === 1 ? "contract" : "contracts") : "sh";

  const tranches = planRaw
    ? planRaw.split("|").map((s) => s.trim()).filter(Boolean)
    : [];

  return (
    <div
      style={{
        backgroundColor: "rgba(99,102,241,0.045)",
        border: "1px solid rgba(99,102,241,0.18)",
        borderRadius: 10,
        padding: "8px 10px",
        marginBottom: 12,
      }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider" style={{ color: "#a5b4fc" }}>
          {headerLabel}
        </span>
        {qty > 0 && (
          <span className="text-[length:var(--t-xs)] tabular-nums text-slate-300">
            <span className="text-slate-500">total </span>{qty} {unitLabel}
          </span>
        )}
      </div>
      {tranches.length > 0 ? (
        <div className="flex flex-col gap-0.5">
          {tranches.map((t, i) => (
            <div key={i} className="flex items-center gap-2 text-[length:var(--t-xs)]">
              <span className="text-slate-500 w-7 shrink-0 tabular-nums">T{i + 1}</span>
              <span className="text-slate-300 leading-snug">{t}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[length:var(--t-xs)] text-slate-500">
          {qty} {unitLabel} — single tranche
        </div>
      )}
    </div>
  );
}

function OptionsSpecRow({ decision }: { decision: DecisionRow }) {
  const strike = Number(decision.strike) || 0;
  const conf = Number(decision.thesis_confidence) || 0;
  const confPct = Math.max(0, Math.min(1, conf)) * 100;
  const confColor = confPct >= 70 ? "#34d399" : confPct >= 50 ? "#818cf8" : "#fbbf24";
  const yldRaw = decision.annual_yield_pct;
  const yldNum = Number(yldRaw);
  // Suppress yield row when value is zero/empty/NaN (brain emits 0 for filled positions).
  const showYield = yldRaw !== undefined && yldRaw !== "" && !isNaN(yldNum) && yldNum !== 0;
  const delta = Number(decision.delta);
  const ivrRaw = decision.iv_rank;
  const ivrNum = Number(ivrRaw);
  // Suppress IVR (render "—") when value is zero/empty/NaN.
  const showIvr = ivrRaw !== undefined && ivrRaw !== "" && !isNaN(ivrNum) && ivrNum !== 0;

  return (
    <div
      style={{
        backgroundColor: "rgba(255,255,255,0.028)",
        border: "1px solid rgba(255,255,255,0.085)",
        borderRadius: 10,
        padding: "8px 10px",
        marginBottom: 12,
      }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-xs)] font-semibold text-slate-200 tabular-nums">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{decision.right}
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-600">exp {fmtExpiry(decision.expiry)}</span>
        </div>
        <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider" style={{ color: "#818cf8" }}>
          {decision.strategy}
        </span>
      </div>
      <div
        className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500"
        style={{ marginBottom: 6 }}
      >
        <span>Premium <span className="text-slate-300 tabular-nums">{fmtMoneyMantissa(decision.premium_per_share)}</span></span>
        {showYield && (
          <span>Yield <span style={{ color: "#34d399" }} className="tabular-nums font-semibold">{fmtPct(yldNum)}</span></span>
        )}
        <span>Δ <span className="text-slate-300 tabular-nums">{isNaN(delta) ? "—" : delta.toFixed(2)}</span></span>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-[length:var(--t-2xs)] text-slate-500">
          <span>BE <span className="text-slate-300 tabular-nums">{fmtMoney(decision.breakeven)}</span></span>
          <span>IVR <span className="text-slate-300 tabular-nums">{showIvr ? ivrNum.toFixed(0) : "—"}</span></span>
        </div>
        {decision.thesis_confidence && (
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[length:var(--t-2xs)] text-slate-500">Conf</span>
            <div
              style={{
                width: 40,
                height: 4,
                borderRadius: 2,
                backgroundColor: "rgba(255,255,255,0.05)",
                overflow: "hidden",
              }}
            >
              <div style={{ height: "100%", width: `${confPct}%`, backgroundColor: confColor }} />
            </div>
            <span className="text-[length:var(--t-2xs)] font-semibold tabular-nums text-slate-300">
              {confPct.toFixed(0)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function CardActions({ ticker }: { ticker: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!ticker) return;
    try {
      await navigator.clipboard.writeText(ticker);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable on http or older iOS — silently ignore.
    }
  };

  const handleOpenIbkr = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!ticker) return;
    const url = `https://www.interactivebrokers.com/en/index.php?f=2222&exch=NYSE&symbol=${encodeURIComponent(ticker)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // Stop pointer/touch events from bubbling so the parent card's tap doesn't fire.
  const stopAll = (e: React.SyntheticEvent) => e.stopPropagation();

  const baseBtn =
    "flex items-center gap-1 px-2 py-1 rounded-md border border-white/5 bg-white/3 hover:bg-white/5 active:bg-white/7 transition-colors text-[length:var(--t-2xs)]";

  return (
    <div
      className="flex items-center gap-1.5 shrink-0"
      onPointerDown={stopAll}
      onMouseDown={stopAll}
      onTouchStart={stopAll}
    >
      <button
        type="button"
        onClick={handleCopy}
        aria-label={`Copy ticker ${ticker}`}
        className={baseBtn}
      >
        {copied ? (
          <>
            <Check size={11} className="text-emerald-400" />
            <span className="text-emerald-400 font-medium">Copied</span>
          </>
        ) : (
          <>
            <Copy size={11} className="text-slate-500" />
            <span className="text-slate-400 font-medium">Copy</span>
          </>
        )}
      </button>
      <button
        type="button"
        onClick={handleOpenIbkr}
        aria-label={`Open ${ticker} in IBKR`}
        className={baseBtn}
      >
        <ExternalLink size={11} className="text-slate-500" />
        <span className="text-slate-400 font-medium">IBKR</span>
      </button>
    </div>
  );
}

/**
 * Compact "as of Nd ago" chip — color-coded by staleness so the user can see
 * at a glance when brain prose has been recycled past its useful life.
 *   - 0d   → slate (today)
 *   - 1-3d → muted slate
 *   - 4-7d → amber (a touch stale)
 *   - 8d+  → red (clearly stale)
 */
function AgeChip({ date }: { date: string }) {
  const n = daysAgo(date);
  let label: string;
  if (n === 0) label = "now";
  else label = `${n}d`;

  let cls = "bg-white/5 text-slate-500 border-white/5";
  if (n >= 8) cls = "bg-red-500/10 text-red-400 border-red-500/20";
  else if (n >= 4) cls = "bg-amber-500/10 text-amber-400 border-amber-500/20";

  return (
    <span
      className={`px-1.5 py-0.5 rounded-md border text-[length:var(--t-2xs)] font-medium tabular-nums ${cls}`}
      aria-label={n === 0 ? "Refreshed today" : `Refreshed ${n} days ago`}
    >
      {label}
    </span>
  );
}

/**
 * Resolve the live current price for a decision ticker.
 *   - First check positions (held tickers — most authoritative because IBKR-fed)
 *   - Fall back to technical_scores (catches anything in the daily scan)
 *   - Returns undefined if the ticker isn't anywhere — overlay then renders nothing.
 */
function lookupCurrentPrice(
  ticker: string,
  casparPositions: PositionRow[],
  sarahPositions: PositionRow[],
  technicalScores: TechnicalScoreRow[],
): number | undefined {
  if (!ticker) return undefined;
  const t = ticker.toUpperCase();
  const fromPos = (rows: PositionRow[]) => rows.find((r) => r.ticker?.toUpperCase() === t);
  const cas = fromPos(casparPositions);
  if (cas) {
    const n = Number(cas.last);
    if (!isNaN(n) && n > 0) return n;
  }
  const sar = fromPos(sarahPositions);
  if (sar) {
    const n = Number(sar.last);
    if (!isNaN(n) && n > 0) return n;
  }
  const tech = technicalScores.find((r) => r.ticker?.toUpperCase() === t);
  if (tech) {
    const n = Number(tech.close);
    if (!isNaN(n) && n > 0) return n;
  }
  return undefined;
}

/**
 * Live-price overlay rendered below the thesis. Shows current underlying,
 * delta vs. the brain-emitted entry, and a verdict label so stale prose
 * ("MDT $83.49 IN $84 entry zone") is contradicted on the same row when
 * MDT actually trades $78.24.
 *
 * If no current price is available, returns null — no empty space.
 */
function PriceOverlay({
  current,
  decision,
}: {
  current: number;
  decision: DecisionRow;
}) {
  const entry = Number(decision.entry);
  if (!entry || isNaN(entry) || entry <= 0) return null;

  const distancePct = ((current - entry) / entry) * 100;
  const strategy = decision.strategy ?? "";
  const isOptionStrategy = OPTIONS_STRATEGIES.includes(strategy);
  const isTrim = strategy === "TRIM";

  // Implied stop: 5% below entry for shares, 8% for blue-chip-style entries.
  // (Brain doesn't emit stop directly — these are conservative defaults that
  // match the 5/8% floors used elsewhere in exit-planning.)
  const stopPct = decision.bucket?.toLowerCase() === "blue_chip" ? 0.92 : 0.95;

  let color = "text-slate-500";
  let label = "";

  if (isOptionStrategy) {
    // For CSP/CC/PMCC the `entry` field is the underlying reference price.
    // Skip verdict labels — just show now / Δ for context.
    label = "";
    color = "text-slate-400";
  } else if (isTrim) {
    // TRIM: brain wants to sell at-or-above entry → green when current >= entry.
    if (current >= entry) {
      color = "text-emerald-400";
      label = "ready";
    } else if (distancePct >= -2) {
      color = "text-amber-400";
      label = "near zone";
    } else {
      color = "text-slate-500";
      label = "below";
    }
  } else {
    // BUY_DIP / share entry: brain wants to buy at-or-below entry.
    if (current <= entry * stopPct) {
      color = "text-red-400";
      label = "past stop";
    } else if (current <= entry) {
      color = "text-emerald-400";
      label = "in zone";
    } else if (distancePct <= 2) {
      color = "text-amber-400";
      label = "near zone";
    } else {
      color = "text-slate-500";
      label = "missed";
    }
  }

  const sign = distancePct >= 0 ? "+" : "";
  const entryStr = entry.toFixed(entry < 10 ? 2 : entry < 100 ? 2 : 0);

  return (
    <div
      className={`flex items-center flex-wrap gap-x-2 gap-y-0.5 text-[length:var(--t-2xs)] tabular-nums mb-3 ${color}`}
      style={{ marginTop: -4 }}
    >
      <span>
        now <span className="font-semibold">${current.toFixed(2)}</span>
      </span>
      <span className="text-slate-700">·</span>
      <span>
        {sign}
        {distancePct.toFixed(1)}% vs entry ${entryStr}
      </span>
      {label && (
        <>
          <span className="text-slate-700">·</span>
          <span className="font-medium">{label}</span>
        </>
      )}
    </div>
  );
}

/**
 * TradingView 26-indicator consensus chip — renders 1d + 1W recommendations
 * side-by-side with color-coding. Amber warning icon when timeframes
 * disagree directionally (one BUY-side, other SELL-side).
 *
 * Returns null if neither timeframe has data → no empty space.
 */
function TvConsensusChip({ consensus }: { consensus: TvConsensus | undefined }) {
  if (!consensus || (!consensus.daily && !consensus.weekly)) return null;

  // Color-mapping per recommendation label.
  const recColor = (rec: string | undefined): string => {
    const r = (rec ?? "").toUpperCase();
    if (r === "STRONG_BUY" || r === "BUY") return "text-emerald-400";
    if (r === "STRONG_SELL" || r === "SELL") return "text-red-400";
    if (r === "NEUTRAL") return "text-slate-400";
    return "text-slate-600"; // ERROR / unknown
  };

  // Side classification for divergence detection.
  const recSide = (rec: string | undefined): "buy" | "sell" | "neutral" | "unknown" => {
    const r = (rec ?? "").toUpperCase();
    if (r === "STRONG_BUY" || r === "BUY") return "buy";
    if (r === "STRONG_SELL" || r === "SELL") return "sell";
    if (r === "NEUTRAL") return "neutral";
    return "unknown";
  };

  // Compact label rendering — drop the STRONG_ prefix to save space.
  const fmtRec = (rec: string | undefined): string => {
    const r = (rec ?? "").toUpperCase();
    if (r === "STRONG_BUY") return "STR BUY";
    if (r === "STRONG_SELL") return "STR SELL";
    if (!r || r.startsWith("ERROR")) return "—";
    return r;
  };

  const dailyRec = consensus.daily?.recommendation;
  const weeklyRec = consensus.weekly?.recommendation;
  const dailySide = recSide(dailyRec);
  const weeklySide = recSide(weeklyRec);

  // TF divergence: one side BUY, the other SELL.
  const isDivergent =
    (dailySide === "buy" && weeklySide === "sell") ||
    (dailySide === "sell" && weeklySide === "buy");

  // Counts (approximated server-side; rendered as "buy/26").
  const dailyBuy = Number(consensus.daily?.buy_count ?? 0);
  const weeklyBuy = Number(consensus.weekly?.buy_count ?? 0);

  return (
    <div className="flex items-center flex-wrap gap-x-2 gap-y-1 mb-3 text-[length:var(--t-2xs)]">
      <span className="text-slate-600 font-semibold uppercase tracking-wider">TV</span>
      {consensus.daily && (
        <span className="flex items-center gap-1">
          <span className="text-slate-600">1d</span>
          <span className={`font-semibold tabular-nums ${recColor(dailyRec)}`}>
            {fmtRec(dailyRec)}
          </span>
          {!isNaN(dailyBuy) && dailyBuy > 0 && (
            <span className="text-slate-600 tabular-nums">{dailyBuy}/26</span>
          )}
        </span>
      )}
      {consensus.weekly && (
        <span className="flex items-center gap-1">
          <span className="text-slate-700">·</span>
          <span className="text-slate-600">1W</span>
          <span className={`font-semibold tabular-nums ${recColor(weeklyRec)}`}>
            {fmtRec(weeklyRec)}
          </span>
          {!isNaN(weeklyBuy) && weeklyBuy > 0 && (
            <span className="text-slate-600 tabular-nums">{weeklyBuy}/26</span>
          )}
        </span>
      )}
      {isDivergent && (
        <span
          className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20"
          title="Timeframe divergence: daily and weekly disagree"
        >
          <AlertCircle size={10} />
          <span className="font-medium">TF div</span>
        </span>
      )}
    </div>
  );
}

function DecisionCard({
  decision,
  onTap,
  currentPrice,
  tvConsensus,
  earnings,
  analyst,
  news,
  insider,
  exposurePosture,
}: {
  decision: DecisionRow;
  onTap: () => void;
  currentPrice: number | undefined;
  tvConsensus: TvConsensus | undefined;
  earnings?: EarningsRow;
  analyst?: AnalystConsensusRow;
  news?: NewsSummary;
  insider?: InsiderSummary;
  exposurePosture?: ExposurePostureRow | null;
}) {
  const status = STATUS_CONFIG[decision.status?.toLowerCase()] ?? DEFAULT_STATUS;
  const Icon = status.icon;
  const conv = Math.round(Number(decision.conv) || 0);
  const showOptionsSpec = !!decision.strategy && OPTIONS_STRATEGIES.includes(decision.strategy);
  // Real-time trigger evaluation (only meaningful for status="watching").
  // Returns dormant when not watching or no data; the badge renders null
  // for dormant so cards stay clean.
  const triggerEval = evaluateTrigger(decision, currentPrice, exposurePosture ?? null, tvConsensus);
  // Show the chip strip only when at least one chip has data, so cards
  // with no Finnhub context (e.g. SGX tickers TV doesn't cover) stay clean.
  const hasInfoChips = !!(earnings || analyst || news || insider);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onTap();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onTap}
      onKeyDown={onKey}
      className={`w-full text-left glass rounded-2xl p-4 border ${status.border} active:bg-white/3 transition-colors cursor-pointer`}
    >
      {/* Header: ticker + status */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-xl bg-slate-700/50 flex items-center justify-center">
            <span className="text-[length:var(--t-xs)] font-bold text-slate-200">
              {decision.ticker?.slice(0, 4)}
            </span>
          </div>
          <div>
            <div className="text-[length:var(--t-sm)] font-semibold text-slate-100">{decision.ticker}</div>
            <div className="text-[length:var(--t-2xs)] text-slate-500 uppercase">{decision.account || "—"}</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {/* Real-time trigger pill — surfaces ACT NOW the moment the
              brain's watching-row trigger fires, without waiting for
              the next WSR re-emission. Renders null when dormant. */}
          <TriggerBadge evaluation={triggerEval} />
          <AgeChip date={decision.date} />
          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${status.bg}`}>
            <Icon size={12} className={status.text} />
            <span className={`text-[length:var(--t-xs)] font-semibold ${status.text}`}>{status.label}</span>
          </div>
          <ChevronRight size={14} className="text-slate-600" />
        </div>
      </div>

      {/* Thesis */}
      <p className="text-[length:var(--t-sm)] text-slate-300 leading-relaxed mb-3">{decision.thesis_1liner}</p>

      {/* Live-price overlay — surfaces ground truth even when brain prose lags. */}
      {currentPrice !== undefined && <PriceOverlay current={currentPrice} decision={decision} />}

      {/* TradingView 26-indicator consensus (1d + 1W) — external sanity-check
          on the brain's thesis. Amber warning if timeframes disagree. */}
      <TvConsensusChip consensus={tvConsensus} />

      {/* Finnhub-derived context chips (Phase 6) — earnings inside DTE,
          Wall St consensus, news sentiment, insider flow. Each chip is
          null-safe so the strip is hidden when the brain has no signal. */}
      {hasInfoChips && (
        <div className="flex items-center flex-wrap gap-1.5 mb-3">
          <EarningsBadge earnings={earnings} />
          <AnalystChip analyst={analyst} />
          <NewsSentimentDot news={news} />
          <InsiderFlowIcon insider={insider} />
        </div>
      )}

      {/* Accumulation/tranche plan (share recs only — option recs leave it empty) */}
      <AccumulationPlanRow decision={decision} />

      {/* Options-spec sub-row (only for option strategies) */}
      {showOptionsSpec && <OptionsSpecRow decision={decision} />}

      {/* Bucket + metrics row + actions */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          {decision.bucket && (
            <span className="text-[length:var(--t-2xs)] font-medium text-slate-500 uppercase bg-white/5 px-2 py-0.5 rounded">
              {decision.bucket}
            </span>
          )}
          {conv > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[length:var(--t-2xs)] text-slate-500">Conv</span>
              <ConvictionDots level={conv} />
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 text-[length:var(--t-xs)] tabular-nums">
          {decision.entry && (
            <span className="text-slate-500">
              Entry <span className="text-slate-300">${Number(decision.entry).toFixed(2)}</span>
            </span>
          )}
          {decision.target && (
            <span className="text-slate-500">
              Target <span className="text-emerald-400/80">${Number(decision.target).toFixed(2)}</span>
            </span>
          )}
        </div>
      </div>

      {/* Action strip */}
      <div className="flex items-center justify-end mt-2.5 pt-2.5 border-t border-white/5">
        <CardActions ticker={decision.ticker} />
      </div>

      {/* Decision feedback loop — Filled / Killed / Defer.
          Records to localStorage. Renders running P&L when filled. */}
      <DecisionActionRow decision={decision} currentPrice={currentPrice} />
    </div>
  );
}

function EmptyState() {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-6">
        <div className="w-12 h-12 rounded-2xl bg-slate-700/50 flex items-center justify-center">
          <Target size={20} className="text-slate-500" />
        </div>
        <div className="text-center">
          <p className="text-[length:var(--t-sm)] font-medium text-slate-400">No decisions yet</p>
          <p className="text-[length:var(--t-xs)] text-slate-500 mt-0.5">
            Decisions from WSR will appear here
          </p>
        </div>
      </div>
    </Card>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-1">
      <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">{count}</span>
    </div>
  );
}

// Sort key: pending → watching → filled → killed/expired → unknown
const STATUS_SORT_RANK: Record<string, number> = {
  pending: 0,
  watching: 1,
  filled: 2,
  killed: 3,
  expired: 3,
};
function statusSortKey(status: string | undefined): number {
  return STATUS_SORT_RANK[(status ?? "").toLowerCase()] ?? 4;
}

export function DecisionsPage({
  decisions,
  technicalScores,
  technicalScoresHistory,
  optionsDefense,
  wheelNextLeg,
  exitPlans,
  casparPositions,
  sarahPositions,
  exposurePosture,
  casparSnapshot,
  sarahSnapshot,
  tvSignals,
  earnings,
  analystByTicker,
  newsByTicker,
  insiderByTicker,
  screenCandidates,
}: {
  decisions: DecisionRow[];
  technicalScores?: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
  optionsDefense?: OptionsDefenseRow[];
  wheelNextLeg?: WheelNextLegRow[];
  exitPlans?: ExitPlanRow[];
  casparPositions?: PositionRow[];
  sarahPositions?: PositionRow[];
  exposurePosture?: ExposurePostureRow | null;
  casparSnapshot?: SnapshotRow | null;
  sarahSnapshot?: SnapshotRow | null;
  tvSignals?: Map<string, TvConsensus>;
  earnings?: EarningsRow[];
  analystByTicker?: Map<string, AnalystConsensusRow>;
  newsByTicker?: Map<string, NewsSummary>;
  insiderByTicker?: Map<string, InsiderSummary>;
  screenCandidates?: ScreenCandidateRow[];
}) {
  const [selected, setSelected] = useState<DecisionRow | null>(null);
  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) techByTicker.set(t.ticker, t);

  // Build per-ticker upcoming-earnings lookup (next 30 days only). Uses
  // the closest-future earnings row per ticker so multi-quarter rows
  // don't fight each other.
  const earningsByTicker = new Map<string, EarningsRow>();
  if (earnings && earnings.length) {
    const today = new Date().toISOString().slice(0, 10);
    for (const e of earnings) {
      if (!e.ticker || !e.date || e.date < today) continue;
      const t = e.ticker.toUpperCase();
      const prev = earningsByTicker.get(t);
      if (!prev || e.date < prev.date) earningsByTicker.set(t, e);
    }
  }

  // Resolve live price once per row (positions first, scores fallback).
  const priceFor = (ticker: string) =>
    lookupCurrentPrice(
      ticker,
      casparPositions ?? [],
      sarahPositions ?? [],
      technicalScores ?? [],
    );

  // TV consensus lookup — case-insensitive on ticker.
  const tvFor = (ticker: string): TvConsensus | undefined => {
    if (!tvSignals || !ticker) return undefined;
    return tvSignals.get(ticker.toUpperCase());
  };

  // If we have no WSR decisions, still show BuyRecommendationsCard if we have scores
  const showBuyRecs = (technicalScores?.length ?? 0) > 0;

  // Split decisions by strategy family
  const activeOptions = decisions
    .filter((d) => OPTIONS_STRATEGIES.includes(d.strategy ?? ""))
    .sort((a, b) => statusSortKey(a.status) - statusSortKey(b.status));

  const shareDecisions = decisions
    .filter((d) => SHARE_STRATEGIES.includes(d.strategy ?? ""))
    .sort((a, b) => statusSortKey(a.status) - statusSortKey(b.status));

  // Catch-all bucket for any unrecognised strategies — append to share section.
  const unrecognised = decisions.filter(
    (d) => !OPTIONS_STRATEGIES.includes(d.strategy ?? "") && !SHARE_STRATEGIES.includes(d.strategy ?? ""),
  );
  const shareDecisionsAll = [...shareDecisions, ...unrecognised].sort(
    (a, b) => statusSortKey(a.status) - statusSortKey(b.status),
  );

  // Count by status for the summary pills (whole page).
  const counts: Record<string, number> = {};
  for (const d of decisions) {
    const s = d.status?.toLowerCase() || "unknown";
    counts[s] = (counts[s] || 0) + 1;
  }

  let fadeIdx = 1;
  const nextFade = () => `fade-up fade-up-${Math.min(fadeIdx++, 4)}`;

  return (
    <>
      <div className="px-4 pb-4 flex flex-col gap-4">
        {/* Exposure Budget — top-of-page strip. Always visible across
            all status filters; renders graceful fallback if posture
            sheet is empty (cron hasn't run yet). */}
        <div className={nextFade()}>
          <ExposureBudgetCard
            posture={exposurePosture ?? null}
            caspar={casparSnapshot ?? null}
            sarah={sarahSnapshot ?? null}
          />
        </div>

        {/* Action Queue — only renders when non-empty */}
        <div className={nextFade()}>
          <ActionQueueCard
            optionsDefense={optionsDefense ?? []}
            wheelNextLeg={wheelNextLeg ?? []}
            exitPlans={exitPlans ?? []}
            technicalScores={technicalScores}
            technicalScoresHistory={technicalScoresHistory}
          />
        </div>

        {/* Buy recommendations from daily technical scan */}
        {showBuyRecs && (
          <div className={nextFade()}>
            <BuyRecommendationsCard
              technicalScores={technicalScores ?? []}
              technicalScoresHistory={technicalScoresHistory}
            />
          </div>
        )}

        {/* Fresh Ideas — weekly vcp + canslim screener output. Renders the
            "no candidates yet" empty-state if the cron hasn't run; otherwise
            shows top 8 per source. */}
        <div className={nextFade()}>
          <FreshIdeasCard
            candidates={screenCandidates ?? []}
            technicalScores={technicalScores ?? []}
            technicalScoresHistory={technicalScoresHistory}
          />
        </div>

        {decisions.length > 0 ? (
          <>
            {/* Summary pills */}
            <div className="flex gap-2 overflow-x-auto no-scrollbar py-1 -mx-1 px-1">
              {Object.entries(counts).map(([status, count]) => {
                const cfg = STATUS_CONFIG[status] ?? DEFAULT_STATUS;
                return (
                  <div
                    key={status}
                    className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full ${cfg.bg} border ${cfg.border}`}
                  >
                    <span className={`text-[length:var(--t-xs)] font-semibold ${cfg.text}`}>{count}</span>
                    <span className={`text-[length:var(--t-2xs)] ${cfg.text} opacity-70`}>{cfg.label}</span>
                  </div>
                );
              })}
            </div>

            {/* Active Options section */}
            {activeOptions.length > 0 && (
              <div className="flex flex-col gap-2.5">
                <SectionHeader label="Active Options" count={activeOptions.length} />
                {activeOptions.map((d, i) => (
                  <div key={`opt-${d.ticker}-${d.date}-${i}`}>
                    <DecisionCard
                      decision={d}
                      onTap={() => setSelected(d)}
                      currentPrice={priceFor(d.ticker)}
                      tvConsensus={tvFor(d.ticker)}
                      earnings={earningsByTicker.get((d.ticker || "").toUpperCase())}
                      analyst={analystByTicker?.get((d.ticker || "").toUpperCase())}
                      news={newsByTicker?.get((d.ticker || "").toUpperCase())}
                      insider={insiderByTicker?.get((d.ticker || "").toUpperCase())}
                      exposurePosture={exposurePosture}
                    />
                  </div>
                ))}
              </div>
            )}

            {/* Share Decisions section */}
            {shareDecisionsAll.length > 0 && (
              <div className="flex flex-col gap-2.5">
                <SectionHeader label="Share Decisions" count={shareDecisionsAll.length} />
                {shareDecisionsAll.map((d, i) => (
                  <div key={`share-${d.ticker}-${d.date}-${i}`}>
                    <DecisionCard
                      decision={d}
                      onTap={() => setSelected(d)}
                      currentPrice={priceFor(d.ticker)}
                      tvConsensus={tvFor(d.ticker)}
                      earnings={earningsByTicker.get((d.ticker || "").toUpperCase())}
                      analyst={analystByTicker?.get((d.ticker || "").toUpperCase())}
                      news={newsByTicker?.get((d.ticker || "").toUpperCase())}
                      insider={insiderByTicker?.get((d.ticker || "").toUpperCase())}
                      exposurePosture={exposurePosture}
                    />
                  </div>
                ))}
              </div>
            )}
          </>
        ) : !showBuyRecs && (
          <EmptyState />
        )}
      </div>

      {selected && (
        <StockDetail
          decision={selected}
          ticker={selected.ticker}
          techScore={techByTicker.get(selected.ticker)}
          techHistory={technicalScoresHistory}
          currency={selected.account?.toLowerCase() === "sarah" ? "SGD" : "USD"}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
