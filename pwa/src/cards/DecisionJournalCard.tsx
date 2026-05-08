/**
 * Decision Journal — running ledger of every action recorded via the
 * DecisionActionRow buttons on the Decisions tab.
 *
 * For each action: shows date, ticker, account, action type, fill price,
 * qty, days held, current price, and unrealised P&L. Filled actions get
 * % and $ colour-coded by sign.
 *
 * The current price comes from the live_prices map (5-min cron). When
 * a ticker isn't in the map (rare — usually because it isn't in the
 * portfolio universe), we show "—" for current and skip P&L.
 *
 * Purpose: closes the action→outcome loop. Now you can see at a glance
 * which calls panned out, which were killed prematurely, etc. — the
 * raw data needed to compute hit-rate over time.
 */
import { useMemo } from "react";
import type { LivePriceRow } from "../data";
import { Card } from "./Card";
import {
  type DecisionAction,
  fillPnl,
} from "../lib/decisionActions";
import { useDecisionActions } from "../lib/useDecisionActions";
import { CheckCircle, XCircle, Clock4, Trash2, NotebookPen } from "lucide-react";
import { numeric } from "../data";

const SHORT_STRATS = ["BUY_DIP", "TRIM"];

function daysSince(iso: string): number {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}

export function DecisionJournalCard({
  livePrices,
}: {
  livePrices: Map<string, LivePriceRow>;
}) {
  const { actions, remove } = useDecisionActions();

  const sortedActions = useMemo(() => {
    return [...actions.values()].sort((a, b) => b.recordedAt.localeCompare(a.recordedAt));
  }, [actions]);

  // Aggregate stats — filled-only.
  const stats = useMemo(() => {
    let filledCount = 0;
    let killedCount = 0;
    let deferredCount = 0;
    let totalPnl = 0;
    let pnlCount = 0;
    let winCount = 0;
    for (const a of sortedActions) {
      if (a.action === "filled") {
        filledCount += 1;
        const live = livePrices.get(a.ticker);
        const cur = live ? numeric(live.last) : undefined;
        const pnl = fillPnl(a, cur);
        if (pnl) {
          totalPnl += pnl.absUsd;
          pnlCount += 1;
          if (pnl.pct >= 0) winCount += 1;
        }
      } else if (a.action === "killed") killedCount += 1;
      else if (a.action === "deferred") deferredCount += 1;
    }
    const hitRate = pnlCount > 0 ? (winCount / pnlCount) * 100 : 0;
    return { filledCount, killedCount, deferredCount, totalPnl, pnlCount, winCount, hitRate };
  }, [sortedActions, livePrices]);

  if (!sortedActions.length) {
    return (
      <Card>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <NotebookPen size={14} className="text-fuchsia-400/70" />
            <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Decision Journal</h2>
          </div>
        </div>
        <p className="text-[length:var(--t-2xs)] text-slate-600 leading-relaxed">
          No actions recorded yet. Mark decisions as Filled / Killed / Deferred
          on the Decisions tab to start building your journal. Filled actions
          show running P&L against the live price feed.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <NotebookPen size={14} className="text-fuchsia-400/70" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Decision Journal</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600">{sortedActions.length} action{sortedActions.length === 1 ? "" : "s"}</span>
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <Metric
          label="Filled"
          value={String(stats.filledCount)}
          sub={stats.pnlCount > 0 ? `${stats.winCount}/${stats.pnlCount} winning` : undefined}
          accent="#34d399"
        />
        <Metric
          label="Hit rate"
          value={stats.pnlCount > 0 ? `${stats.hitRate.toFixed(0)}%` : "—"}
          sub={stats.pnlCount > 0 ? `${stats.pnlCount} priced` : "no prices yet"}
        />
        <Metric
          label="Net P&L"
          value={
            stats.pnlCount > 0
              ? `${stats.totalPnl >= 0 ? "+" : "-"}$${Math.abs(stats.totalPnl).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
              : "—"
          }
          accent={stats.totalPnl >= 0 ? "#34d399" : "#fca5a5"}
          sub="unrealised"
        />
      </div>

      {/* Per-action rows */}
      <div className="rounded-xl overflow-hidden border border-white/5">
        <div className="grid grid-cols-[0.5fr_0.7fr_0.5fr_0.6fr_0.6fr_0.6fr_0.3fr] gap-2 px-3 py-1.5 bg-white/3 text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wider font-semibold">
          <span>Date</span>
          <span>Ticker</span>
          <span>Acct</span>
          <span className="text-right">Fill</span>
          <span className="text-right">Now</span>
          <span className="text-right">P&L</span>
          <span></span>
        </div>
        {sortedActions.map((a) => (
          <JournalRow key={a.decisionKey} action={a} livePrices={livePrices} onUndo={() => remove(a.decisionKey)} />
        ))}
      </div>
    </Card>
  );
}

const ACTION_CONFIG: Record<
  DecisionAction["action"],
  { color: string; icon: typeof CheckCircle }
> = {
  filled:   { color: "#34d399", icon: CheckCircle },
  killed:   { color: "#fca5a5", icon: XCircle },
  deferred: { color: "#fcd34d", icon: Clock4 },
};

function JournalRow({
  action,
  livePrices,
  onUndo,
}: {
  action: DecisionAction;
  livePrices: Map<string, LivePriceRow>;
  onUndo: () => void;
}) {
  const cfg = ACTION_CONFIG[action.action];
  const Icon = cfg.icon;
  const days = daysSince(action.recordedAt);
  const dateLabel = days === 0 ? "today" : days < 30 ? `${days}d` : action.recordedAt.slice(5, 10);

  const live = livePrices.get(action.ticker);
  const currentPrice = live ? numeric(live.last) : undefined;
  const pnl = fillPnl(action, currentPrice);
  const qtyUnit = SHORT_STRATS.includes(action.strategy) ? "sh" : "ct";

  return (
    <div className="grid grid-cols-[0.5fr_0.7fr_0.5fr_0.6fr_0.6fr_0.6fr_0.3fr] gap-2 px-3 py-1.5 text-[length:var(--t-xs)] tabular-nums border-t border-white/5 items-center">
      <span className="text-slate-400">{dateLabel}</span>
      <span className="flex items-center gap-1 min-w-0">
        <Icon size={10} style={{ color: cfg.color }} />
        <span className="text-slate-200 font-medium truncate">{action.ticker}</span>
        {action.strategy && action.strategy !== "BUY_DIP" && (
          <span className="text-slate-600 text-[length:var(--t-2xs)]">{action.strategy}</span>
        )}
      </span>
      <span className="text-slate-500 uppercase text-[length:var(--t-2xs)]">{action.account}</span>
      <span className="text-right text-slate-400">
        {action.fillPrice ? `$${action.fillPrice.toFixed(2)}` : "—"}
        {action.qty ? <span className="text-slate-600 text-[length:var(--t-2xs)]"> · {action.qty}{qtyUnit}</span> : null}
      </span>
      <span className="text-right text-slate-400">
        {currentPrice !== undefined ? `$${currentPrice.toFixed(2)}` : "—"}
      </span>
      <span
        className="text-right font-semibold"
        style={{ color: pnl ? (pnl.pct >= 0 ? "#34d399" : "#fca5a5") : "#64748b" }}
      >
        {pnl ? `${pnl.pct >= 0 ? "+" : ""}${pnl.pct.toFixed(1)}%` : "—"}
      </span>
      <button
        type="button"
        className="text-slate-600 hover:text-red-400 active:scale-90 transition justify-self-end"
        onClick={onUndo}
        aria-label="Remove journal entry"
        title="Remove entry"
      >
        <Trash2 size={10} />
      </button>
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div
      className="rounded-xl p-2.5"
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      <div className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500 mb-0.5">
        {label}
      </div>
      <div
        className="text-[length:var(--t-md)] font-bold tabular-nums"
        style={{ color: accent ?? "rgb(226 232 240)" }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[length:var(--t-2xs)] text-slate-500 mt-0.5">
          {sub}
        </div>
      )}
    </div>
  );
}
