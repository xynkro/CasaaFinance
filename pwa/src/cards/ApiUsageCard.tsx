import type { ApiUsageRow } from "../data";
import { DollarSign, Brain, Clock } from "lucide-react";

/**
 * API Usage card — Anthropic spend across brain workflows. Lives in
 * the Settings tab so the user can see what each WSR / Daily Brief
 * costs and what month-to-date spend looks like.
 *
 * Source: `api_usage` sheet, populated by
 * `scripts/api_usage_scrape.py` from gh workflow run logs.
 *
 * Shows three sections:
 *   1. Top metrics — MTD total + current-week total + per-run avg
 *   2. Per-workflow breakdown — workflow × runs × $ × avg/run
 *   3. Last 10 runs — date, workflow, $, turns, duration
 *
 * Renders empty-state when no rows yet (first deploy, scraper hasn't
 * run, or all brain runs predate claude-code-action).
 */
export function ApiUsageCard({ rows }: { rows: ApiUsageRow[] }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="glass rounded-2xl p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider">
            API Usage
          </h3>
          <DollarSign size={14} className="text-slate-600" />
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 leading-relaxed">
          No API usage data yet. Run{" "}
          <code className="text-slate-400">casaa api-usage</code> to scrape
          recent brain runs into the api_usage sheet.
        </p>
      </div>
    );
  }

  // Filter helpers — buckets by SGT date prefix (ISO leading "YYYY-MM-DD")
  const today = new Date();
  const monthPrefix = today.toISOString().slice(0, 7); // "2026-05"
  const weekStart = new Date(today);
  weekStart.setUTCDate(today.getUTCDate() - 7);
  const weekStartStr = weekStart.toISOString().slice(0, 10);

  const num = (s?: string) => Number(s) || 0;

  const mtdRows = rows.filter((r) => (r.date || "").startsWith(monthPrefix));
  const weekRows = rows.filter((r) => (r.date || "").slice(0, 10) >= weekStartStr);

  const mtdTotal = mtdRows.reduce((s, r) => s + num(r.total_cost_usd), 0);
  const weekTotal = weekRows.reduce((s, r) => s + num(r.total_cost_usd), 0);
  const overallAvg = rows.length
    ? rows.reduce((s, r) => s + num(r.total_cost_usd), 0) / rows.length
    : 0;

  // Per-workflow aggregate (over the FULL retained history)
  const byWorkflow = new Map<
    string,
    { count: number; total: number; turns: number; durMs: number }
  >();
  for (const r of rows) {
    const wf = r.workflow || "?";
    const cur = byWorkflow.get(wf) ?? { count: 0, total: 0, turns: 0, durMs: 0 };
    cur.count += 1;
    cur.total += num(r.total_cost_usd);
    cur.turns += num(r.num_turns);
    cur.durMs += num(r.duration_ms);
    byWorkflow.set(wf, cur);
  }
  const workflowRows = [...byWorkflow.entries()]
    .map(([wf, agg]) => ({
      workflow: wf,
      count: agg.count,
      total: agg.total,
      avg: agg.total / Math.max(agg.count, 1),
      avgDurSec: agg.durMs / Math.max(agg.count, 1) / 1000,
    }))
    .sort((a, b) => b.total - a.total);

  // Last 10 runs
  const recent = [...rows]
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
    .slice(0, 10);

  const fmt = (n: number, dp = 2) => `$${n.toFixed(dp)}`;

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider">
          API Usage
        </h3>
        <DollarSign size={14} className="text-emerald-400/70" />
      </div>
      <p className="text-[length:var(--t-xs)] text-slate-500 mb-4 leading-relaxed">
        Anthropic API spend across brain workflows (Daily Brief, WSR
        Lite, WSR Full, Market Scan). Finnhub, TradingView, Yahoo are
        free tier so excluded. Refresh via{" "}
        <code className="text-slate-400">casaa api-usage</code>.
      </p>

      {/* Top metrics */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <Metric
          label="Month to date"
          value={fmt(mtdTotal)}
          sub={`${mtdRows.length} runs`}
          accent="#34d399"
        />
        <Metric
          label="Last 7 days"
          value={fmt(weekTotal)}
          sub={`${weekRows.length} runs`}
        />
        <Metric
          label="Avg / run"
          value={fmt(overallAvg)}
          sub={`${rows.length} total`}
        />
      </div>

      {/* Per-workflow */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2">
          <Brain size={11} className="text-indigo-300/70" />
          <span className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500">
            By workflow
          </span>
        </div>
        <div className="rounded-xl overflow-hidden border border-white/5">
          <div className="grid grid-cols-[1.5fr_0.5fr_0.8fr_0.7fr] gap-2 px-3 py-1.5 bg-white/3 text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wider font-semibold">
            <span>Workflow</span>
            <span className="text-right">Runs</span>
            <span className="text-right">Total</span>
            <span className="text-right">Avg</span>
          </div>
          {workflowRows.map((w) => (
            <div
              key={w.workflow}
              className="grid grid-cols-[1.5fr_0.5fr_0.8fr_0.7fr] gap-2 px-3 py-1.5 text-[length:var(--t-xs)] tabular-nums border-t border-white/5"
            >
              <span className="text-slate-200 font-medium">{w.workflow}</span>
              <span className="text-right text-slate-400">{w.count}</span>
              <span className="text-right text-slate-200 font-semibold">
                {fmt(w.total)}
              </span>
              <span className="text-right text-slate-500">{fmt(w.avg)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recent runs */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Clock size={11} className="text-amber-300/70" />
          <span className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500">
            Last 10 runs
          </span>
        </div>
        <div className="rounded-xl overflow-hidden border border-white/5">
          <div className="grid grid-cols-[0.9fr_1.1fr_0.7fr_0.5fr_0.5fr] gap-2 px-3 py-1.5 bg-white/3 text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wider font-semibold">
            <span>Date</span>
            <span>Workflow</span>
            <span className="text-right">Cost</span>
            <span className="text-right">Turns</span>
            <span className="text-right">Dur</span>
          </div>
          {recent.map((r) => (
            <div
              key={r.run_id}
              className="grid grid-cols-[0.9fr_1.1fr_0.7fr_0.5fr_0.5fr] gap-2 px-3 py-1.5 text-[length:var(--t-xs)] tabular-nums border-t border-white/5"
              title={`run_id ${r.run_id} · model ${r.model} · ${r.status}`}
            >
              <span className="text-slate-400">{r.date.slice(5, 10)}</span>
              <span className="text-slate-200 truncate">{r.workflow}</span>
              <span className="text-right text-slate-200 font-semibold">
                {fmt(num(r.total_cost_usd))}
              </span>
              <span className="text-right text-slate-500">{r.num_turns}</span>
              <span className="text-right text-slate-500">
                {(num(r.duration_ms) / 1000 / 60).toFixed(1)}m
              </span>
            </div>
          ))}
        </div>
      </div>
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
