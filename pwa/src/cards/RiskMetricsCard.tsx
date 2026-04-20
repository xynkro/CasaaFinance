import type { SnapshotRow, MacroRow } from "../data";
import { Card } from "./Card";
import { Activity, TrendingUp, TrendingDown, AlertTriangle, Scale } from "lucide-react";

// ---- Math helpers ----

function sortedByDate<T extends { date: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => a.date.localeCompare(b.date));
}

function dailyReturns(rows: SnapshotRow[]): number[] {
  const sorted = sortedByDate(rows);
  const returns: number[] = [];
  for (let i = 1; i < sorted.length; i++) {
    const prev = Number(sorted[i - 1].net_liq);
    const curr = Number(sorted[i].net_liq);
    if (prev > 0 && curr > 0) returns.push((curr - prev) / prev);
  }
  return returns;
}

function mean(arr: number[]): number {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function stdev(arr: number[]): number {
  if (arr.length < 2) return 0;
  const m = mean(arr);
  const sq = arr.map((v) => (v - m) ** 2);
  return Math.sqrt(sq.reduce((a, b) => a + b, 0) / (arr.length - 1));
}

/** Annualized Sharpe ratio assuming 252 trading days, risk-free rate = 4.5% */
function sharpe(returns: number[], rfAnnual = 0.045): number {
  if (returns.length < 5) return 0;
  const avg = mean(returns);
  const sd = stdev(returns);
  if (sd === 0) return 0;
  const rfDaily = rfAnnual / 252;
  return ((avg - rfDaily) / sd) * Math.sqrt(252);
}

/** Max drawdown as a fraction (0.15 = 15% max drawdown) */
function maxDrawdown(rows: SnapshotRow[]): { pct: number; peak: number; trough: number } {
  const sorted = sortedByDate(rows);
  let peak = 0;
  let maxDD = 0;
  let peakVal = 0;
  let troughVal = 0;
  for (const r of sorted) {
    const v = Number(r.net_liq);
    if (!v) continue;
    if (v > peak) peak = v;
    if (peak > 0) {
      const dd = (peak - v) / peak;
      if (dd > maxDD) {
        maxDD = dd;
        peakVal = peak;
        troughVal = v;
      }
    }
  }
  return { pct: maxDD, peak: peakVal, trough: troughVal };
}

/** Pearson correlation between two aligned return series */
function correlation(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n < 5) return 0;
  const aa = a.slice(-n);
  const bb = b.slice(-n);
  const ma = mean(aa);
  const mb = mean(bb);
  let num = 0, dA = 0, dB = 0;
  for (let i = 0; i < n; i++) {
    num += (aa[i] - ma) * (bb[i] - mb);
    dA += (aa[i] - ma) ** 2;
    dB += (bb[i] - mb) ** 2;
  }
  if (dA === 0 || dB === 0) return 0;
  return num / Math.sqrt(dA * dB);
}

/** Beta: cov(portfolio, spx) / var(spx) */
function beta(portfolio: number[], spx: number[]): number {
  const n = Math.min(portfolio.length, spx.length);
  if (n < 5) return 0;
  const p = portfolio.slice(-n);
  const s = spx.slice(-n);
  const mp = mean(p);
  const ms = mean(s);
  let cov = 0;
  let vs = 0;
  for (let i = 0; i < n; i++) {
    cov += (p[i] - mp) * (s[i] - ms);
    vs += (s[i] - ms) ** 2;
  }
  return vs === 0 ? 0 : cov / vs;
}

/** Risk score 0-100 based on volatility + drawdown + concentration */
function riskScore(volAnnual: number, ddPct: number, beta: number): { score: number; label: string; color: string } {
  // Each dimension contributes up to ~33 points
  const volPoints = Math.min(33, (volAnnual / 0.5) * 33);          // 50% vol = max
  const ddPoints = Math.min(33, (ddPct / 0.30) * 33);              // 30% DD = max
  const betaPoints = Math.min(34, (Math.abs(beta - 1) / 1.5) * 34 + (beta > 1.5 ? 17 : 0));
  const score = Math.round(volPoints + ddPoints + betaPoints);

  let label: string, color: string;
  if (score >= 70) { label = "HIGH RISK"; color = "text-red-400"; }
  else if (score >= 45) { label = "MODERATE-HIGH"; color = "text-orange-400"; }
  else if (score >= 25) { label = "MODERATE"; color = "text-amber-400"; }
  else if (score >= 12) { label = "CONSERVATIVE"; color = "text-emerald-400"; }
  else { label = "LOW RISK"; color = "text-emerald-400"; }
  return { score, label, color };
}

// ---- Components ----

function MetricCell({
  label,
  value,
  subValue,
  accent,
  tooltip,
}: {
  label: string;
  value: string;
  subValue?: string;
  accent?: string;
  tooltip?: string;
}) {
  return (
    <div className="glass rounded-xl p-3" title={tooltip}>
      <div className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">
        {label}
      </div>
      <div className={`text-base font-bold tabular-nums mt-1 ${accent ?? "text-slate-100"}`}>
        {value}
      </div>
      {subValue && (
        <div className="text-[10px] text-slate-400 mt-0.5">{subValue}</div>
      )}
    </div>
  );
}

export function RiskMetricsCard({
  casparHistory,
  sarahHistory,
  macroHistory,
}: {
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
}) {
  // Combined portfolio = convert Sarah's SGD to USD using USD/SGD, sum with Caspar
  // For simplicity, compute metrics on combined USD-equivalent.
  // When fx data is sparse, fall back to Caspar-only.

  const fxByDate = new Map<string, number>();
  for (const m of macroHistory) {
    const d = m.date.split("T")[0];
    const fx = Number(m.usd_sgd);
    if (fx > 0) fxByDate.set(d, fx);
  }

  // Combined time series
  const dateMap = new Map<string, { caspar: number; sarah: number }>();
  for (const r of casparHistory) {
    const d = r.date.split("T")[0];
    const v = Number(r.net_liq);
    if (!dateMap.has(d)) dateMap.set(d, { caspar: 0, sarah: 0 });
    dateMap.get(d)!.caspar = v;
  }
  for (const r of sarahHistory) {
    const d = r.date.split("T")[0];
    const v = Number(r.net_liq);
    if (!dateMap.has(d)) dateMap.set(d, { caspar: 0, sarah: 0 });
    dateMap.get(d)!.sarah = v;
  }

  const combinedRows: SnapshotRow[] = [];
  for (const [d, { caspar, sarah }] of dateMap.entries()) {
    const fx = fxByDate.get(d) ?? 1.27;
    const sarahUsd = sarah / fx;
    combinedRows.push({
      date: d,
      net_liq: String(caspar + sarahUsd),
      cash: "",
      upl: "",
      upl_pct: "",
    } as SnapshotRow);
  }
  const combined = sortedByDate(combinedRows);

  // Return series
  const combinedRets = dailyReturns(combined);
  const casparRets = dailyReturns(casparHistory);
  const sarahRets = dailyReturns(sarahHistory);

  // SPX returns from macro
  const spxRows = macroHistory
    .filter((m) => Number(m.spx) > 0)
    .map((m) => ({ date: m.date, val: Number(m.spx) }))
    .sort((a, b) => a.date.localeCompare(b.date));
  const spxRets: number[] = [];
  for (let i = 1; i < spxRows.length; i++) {
    const prev = spxRows[i - 1].val;
    const curr = spxRows[i].val;
    if (prev > 0) spxRets.push((curr - prev) / prev);
  }

  // Metrics
  const volAnnualCombined = stdev(combinedRets) * Math.sqrt(252);
  const sharpeCombined = sharpe(combinedRets);
  const dd = maxDrawdown(combined);
  const betaVsSpx = beta(combinedRets, spxRets);
  const corrVsSpx = correlation(combinedRets, spxRets);

  const volCaspar = stdev(casparRets) * Math.sqrt(252);
  const volSarah = stdev(sarahRets) * Math.sqrt(252);

  const risk = riskScore(volAnnualCombined, dd.pct, betaVsSpx);

  // Insufficient data state
  const insufficient = combined.length < 5;

  return (
    <div className="space-y-4">
      {/* Risk Score Hero */}
      <div className="glass-accent rounded-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Scale size={14} style={{ color: "var(--accent)" }} />
            <h2 className="text-sm font-semibold text-slate-100">Portfolio Risk Profile</h2>
          </div>
          {insufficient && (
            <span className="text-[10px] text-amber-400 flex items-center gap-1">
              <AlertTriangle size={10} />
              Need 5+ days data
            </span>
          )}
        </div>

        <div className="flex items-center gap-4">
          {/* Big score ring */}
          <div className="relative shrink-0" style={{ width: 96, height: 96 }}>
            <svg width="96" height="96" className="rotate-[-90deg]">
              <circle cx="48" cy="48" r="40" stroke="rgba(255,255,255,0.08)" strokeWidth="6" fill="none" />
              <circle
                cx="48" cy="48" r="40"
                stroke="currentColor"
                strokeWidth="6"
                fill="none"
                strokeDasharray={2 * Math.PI * 40}
                strokeDashoffset={2 * Math.PI * 40 * (1 - risk.score / 100)}
                strokeLinecap="round"
                className={risk.color}
                style={{ transition: "stroke-dashoffset 1s ease" }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className={`text-2xl font-bold tabular-nums ${risk.color}`}>{risk.score}</div>
              <div className="text-[9px] text-slate-400 font-semibold">/ 100</div>
            </div>
          </div>

          {/* Label + breakdown */}
          <div className="flex-1 min-w-0">
            <div className={`text-base font-bold ${risk.color}`}>{risk.label}</div>
            <p className="text-[11px] text-slate-300 leading-relaxed mt-1">
              Composite of volatility, max drawdown, and market beta. Updated daily.
            </p>
            <div className="grid grid-cols-3 gap-1.5 mt-2 text-[10px]">
              <div>
                <div className="text-slate-400">σ (ann)</div>
                <div className="text-slate-100 font-semibold tabular-nums">
                  {(volAnnualCombined * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-slate-400">Max DD</div>
                <div className={`font-semibold tabular-nums ${dd.pct > 0.15 ? "text-red-400" : "text-slate-100"}`}>
                  {(dd.pct * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-slate-400">β vs SPX</div>
                <div className="text-slate-100 font-semibold tabular-nums">
                  {betaVsSpx.toFixed(2)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Performance Metrics Grid */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Activity size={14} className="text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-100">Performance</h3>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <MetricCell
            label="Sharpe (ann)"
            value={sharpeCombined.toFixed(2)}
            subValue={sharpeCombined > 1 ? "Good risk-adjusted" : sharpeCombined > 0.5 ? "Acceptable" : sharpeCombined > 0 ? "Below target" : "Negative"}
            accent={sharpeCombined > 1 ? "text-emerald-400" : sharpeCombined > 0 ? "text-slate-100" : "text-red-400"}
          />
          <MetricCell
            label="Corr w/ SPX"
            value={corrVsSpx.toFixed(2)}
            subValue={Math.abs(corrVsSpx) > 0.7 ? "Tracks market" : Math.abs(corrVsSpx) > 0.4 ? "Moderate" : "Diversified"}
          />
          <MetricCell
            label="Caspar σ"
            value={`${(volCaspar * 100).toFixed(1)}%`}
            subValue="annualized"
            accent="text-blue-400"
          />
          <MetricCell
            label="Sarah σ"
            value={`${(volSarah * 100).toFixed(1)}%`}
            subValue="annualized"
            accent="text-pink-400"
          />
        </div>
      </Card>

      {/* Drawdown detail */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <TrendingDown size={14} className="text-red-400" />
          <h3 className="text-sm font-semibold text-slate-100">Drawdown Analysis</h3>
        </div>

        <div className="space-y-2 text-[11px]">
          <div className="flex justify-between">
            <span className="text-slate-400">Peak portfolio value</span>
            <span className="text-slate-100 tabular-nums font-semibold">${dd.peak.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Max drawdown trough</span>
            <span className="text-red-400 tabular-nums font-semibold">${dd.trough.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Loss from peak</span>
            <span className={`tabular-nums font-bold ${dd.pct > 0.15 ? "text-red-400" : "text-amber-400"}`}>
              -{(dd.pct * 100).toFixed(2)}%
            </span>
          </div>
        </div>

        {dd.pct > 0.10 && (
          <div className="mt-3 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-start gap-2">
            <AlertTriangle size={11} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-[10px] text-slate-200 leading-relaxed">
              Drawdown exceeds 10%. Review concentration and consider reducing leveraged exposure.
            </p>
          </div>
        )}
      </Card>

      {/* Concentration — how much is in bags vs healthy vs growth */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp size={14} className="text-emerald-400" />
          <h3 className="text-sm font-semibold text-slate-100">Market Sensitivity</h3>
        </div>
        <div className="text-[11px] text-slate-300 leading-relaxed space-y-2">
          <div className="flex justify-between">
            <span className="text-slate-400">If SPX +1%, portfolio expected</span>
            <span className="text-slate-100 tabular-nums font-semibold">
              {betaVsSpx >= 0 ? "+" : ""}{(betaVsSpx * 1).toFixed(2)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">If SPX -5%, portfolio expected</span>
            <span className="text-red-400 tabular-nums font-semibold">
              {(betaVsSpx * -5).toFixed(2)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">If SPX -10%, portfolio expected</span>
            <span className="text-red-400 tabular-nums font-semibold">
              {(betaVsSpx * -10).toFixed(2)}%
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}
