/**
 * Hit-rate dashboard — cuts the Decision Journal by strategy / bucket /
 * source so you can see WHICH calls have actually paid off.
 *
 * Joins:
 *   - DecisionJournal (action.ticker + .strategy, with fillPrice + qty)
 *   - decisionsAll    (full history, indexed by `keyForDecision()`)
 *
 * Computes per cohort:
 *   - count of filled actions
 *   - count winning (running pnl >= 0)
 *   - hit rate (winning / count)
 *   - net unrealised P&L
 *
 * Cohorts shown:
 *   - By strategy (BUY_DIP / CSP / CC / TRIM / PMCC / etc.)
 *   - By bucket   (blue_chip / quality / speculative / etc.)
 *   - By source   (wsr_full / wsr_lite / risk_parity / market_scan / manual)
 *
 * Renders a "needs more data" message until ≥3 filled actions exist —
 * smaller samples are noise.
 */
import { useMemo } from "react";
import type { DecisionRow, LivePriceRow } from "../data";
import { Card } from "./Card";
import {
  type DecisionAction,
  fillPnl,
  keyForDecision,
} from "../lib/decisionActions";
import { useDecisionActions } from "../lib/useDecisionActions";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";
import { numeric } from "../data";

const MIN_SAMPLE = 3;

interface CohortStats {
  label: string;
  count: number;
  winning: number;
  losing: number;
  hitRate: number;     // 0-1
  totalPnl: number;
}

interface JoinedRow {
  action: DecisionAction;
  decision?: DecisionRow;
  pnl: { absUsd: number; pct: number } | null;
}

function buildCohort(
  rows: JoinedRow[],
  groupBy: (r: JoinedRow) => string | undefined,
  maxLabels = 6,
): CohortStats[] {
  const map = new Map<string, { count: number; winning: number; losing: number; total: number }>();
  for (const r of rows) {
    const key = (groupBy(r) || "").trim();
    if (!key) continue;
    const cur = map.get(key) ?? { count: 0, winning: 0, losing: 0, total: 0 };
    cur.count += 1;
    if (r.pnl) {
      cur.total += r.pnl.absUsd;
      if (r.pnl.pct >= 0) cur.winning += 1;
      else cur.losing += 1;
    }
    map.set(key, cur);
  }
  return [...map.entries()]
    .map(([label, s]) => ({
      label,
      count: s.count,
      winning: s.winning,
      losing: s.losing,
      hitRate: s.count > 0 ? s.winning / s.count : 0,
      totalPnl: s.total,
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, maxLabels);
}

export function HitRateCard({
  decisionsAll,
  livePrices,
}: {
  decisionsAll: DecisionRow[];
  livePrices: Map<string, LivePriceRow>;
}) {
  const { actions } = useDecisionActions();

  // Build a decision-key → DecisionRow lookup so we can pull bucket /
  // source / etc. from the brain emission. Note: the same key may appear
  // multiple times in decisionsAll if the brain re-emitted; take the
  // most-recent row (we only need bucket/source which are stable across
  // re-emits).
  const decisionByKey = useMemo(() => {
    const m = new Map<string, DecisionRow>();
    for (const d of decisionsAll) {
      const k = keyForDecision(d);
      const prev = m.get(k);
      if (!prev || d.date > prev.date) m.set(k, d);
    }
    return m;
  }, [decisionsAll]);

  // Filled rows only — kills + defers don't have a P&L outcome.
  const joinedFilled = useMemo<JoinedRow[]>(() => {
    const out: JoinedRow[] = [];
    for (const a of actions.values()) {
      if (a.action !== "filled") continue;
      const live = livePrices.get(a.ticker);
      const cur = live ? numeric(live.last) : undefined;
      out.push({
        action: a,
        decision: decisionByKey.get(a.decisionKey),
        pnl: fillPnl(a, cur),
      });
    }
    return out;
  }, [actions, decisionByKey, livePrices]);

  if (joinedFilled.length < MIN_SAMPLE) {
    return (
      <Card>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Activity size={14} className="text-fuchsia-400/70" />
            <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Hit Rate</h2>
          </div>
          <span className="text-[length:var(--t-2xs)] text-slate-600">
            {joinedFilled.length} / {MIN_SAMPLE} samples
          </span>
        </div>
        <p className="text-[length:var(--t-2xs)] text-slate-600 leading-relaxed">
          Mark at least {MIN_SAMPLE} decisions as Filled to start seeing
          per-strategy / per-bucket / per-source hit rates here. Fewer
          samples than that is noise.
        </p>
      </Card>
    );
  }

  const byStrategy = buildCohort(joinedFilled, (r) => r.action.strategy || "(unknown)");
  const byBucket   = buildCohort(joinedFilled, (r) => r.decision?.bucket);
  const bySource   = buildCohort(joinedFilled, (r) => r.decision?.source);

  // Overall hit rate
  const priced = joinedFilled.filter((r) => r.pnl);
  const overall = priced.length > 0
    ? priced.filter((r) => r.pnl!.pct >= 0).length / priced.length
    : 0;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-fuchsia-400/70" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Hit Rate</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-2xs)] text-slate-600">{priced.length} priced</span>
          <span
            className="text-[length:var(--t-xs)] font-bold tabular-nums"
            style={{ color: overall >= 0.5 ? "#34d399" : "#fca5a5" }}
          >
            {(overall * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-4 leading-relaxed">
        Filled decisions only. P&L is unrealised (current price vs your
        recorded fill price). Higher hit-rate cohorts deserve more
        capital allocation; lower ones are candidates for prompt tuning.
      </p>

      <CohortBlock title="By strategy" cohorts={byStrategy} />
      {byBucket.length > 0 && (
        <div className="mt-3">
          <CohortBlock title="By bucket" cohorts={byBucket} />
        </div>
      )}
      {bySource.length > 0 && (
        <div className="mt-3">
          <CohortBlock title="By source" cohorts={bySource} />
        </div>
      )}
    </Card>
  );
}

function CohortBlock({ title, cohorts }: { title: string; cohorts: CohortStats[] }) {
  return (
    <div>
      <div className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500 mb-1.5">
        {title}
      </div>
      <div className="rounded-xl overflow-hidden border border-white/5">
        <div className="grid grid-cols-[1.5fr_0.5fr_0.7fr_0.8fr] gap-2 px-3 py-1.5 bg-white/3 text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wider font-semibold">
          <span>Cohort</span>
          <span className="text-right">N</span>
          <span className="text-right">Hit</span>
          <span className="text-right">Net</span>
        </div>
        {cohorts.map((c) => (
          <CohortRow key={c.label} cohort={c} />
        ))}
      </div>
    </div>
  );
}

function CohortRow({ cohort }: { cohort: CohortStats }) {
  const hitColor =
    cohort.hitRate >= 0.6 ? "#34d399" :
    cohort.hitRate >= 0.4 ? "#fcd34d" : "#fca5a5";
  const TrendIcon = cohort.totalPnl >= 0 ? TrendingUp : TrendingDown;
  const pnlColor = cohort.totalPnl >= 0 ? "#34d399" : "#fca5a5";

  return (
    <div className="grid grid-cols-[1.5fr_0.5fr_0.7fr_0.8fr] gap-2 px-3 py-1.5 text-[length:var(--t-xs)] tabular-nums border-t border-white/5">
      <span className="text-slate-200 font-medium truncate">{cohort.label}</span>
      <span className="text-right text-slate-400">{cohort.count}</span>
      <span className="text-right font-bold" style={{ color: hitColor }}>
        {(cohort.hitRate * 100).toFixed(0)}%
      </span>
      <span
        className="text-right font-semibold flex items-center justify-end gap-1"
        style={{ color: pnlColor }}
      >
        <TrendIcon size={9} />
        {cohort.totalPnl >= 0 ? "+" : "-"}$
        {Math.abs(cohort.totalPnl).toLocaleString("en-US", { maximumFractionDigits: 0 })}
      </span>
    </div>
  );
}
