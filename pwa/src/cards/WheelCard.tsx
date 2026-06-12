import type { OptionRow, PositionRow, TechnicalScoreRow, ExitPlanRow, OptionsDefenseRow } from "../data";
import { numeric } from "../data";
import { Card } from "./Card";
import { Chip } from "../components/ui";
import { OptionMechanics, numOrUndef, dteClass } from "../components/OptionMechanics";
import { CircleDot, AlertTriangle, TrendingUp, TrendingDown, Shield, Info, Zap } from "lucide-react";
import { useState } from "react";

// ---------- helpers ----------

function fmtExp(expiry: string): string {
  if (!expiry || expiry.length < 8) return "—";
  return `${expiry.slice(4, 6)}/${expiry.slice(6, 8)}`;
}

function fmtStrike(v: string): string {
  const n = Number(v);
  return isNaN(n) || n === 0 ? "—" : `$${n.toFixed(0)}`;
}

function fmtPrice(v: string | number, prefix = "$"): string {
  const n = Number(v);
  return isNaN(n) ? "—" : `${prefix}${n.toFixed(2)}`;
}

// ---------- badges ----------

const MONEYNESS_STYLE: Record<string, string> = {
  ITM: "bg-red-500/15 text-red-400 border-red-500/20",
  ATM: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  OTM: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20",
};

const RISK_STYLE: Record<string, { bg: string; icon: typeof Shield }> = {
  HIGH: { bg: "text-red-400", icon: AlertTriangle },
  MED: { bg: "text-amber-400", icon: AlertTriangle },
  LOW: { bg: "text-emerald-400", icon: Shield },
};

const TREND_STYLE: Record<string, string> = {
  SAFE: "text-emerald-400",
  DRIFTING: "text-slate-400",
  CONVERGING: "text-amber-400",
  BREACHING: "text-red-400",
};

const WHEEL_LEG_LABEL: Record<string, string> = {
  CC: "Covered Call",
  CSP: "Cash-Secured Put",
  NAKED_CALL: "Naked Call",
  LONG_CALL: "Long Call",
  LONG_PUT: "Long Put",
};

// ---------- sub-components ----------

function MoneynessChip({ value }: { value: string }) {
  const style = MONEYNESS_STYLE[value] ?? "bg-slate-500/15 text-slate-400 border-slate-500/20";
  return (
    <Chip pad="md" tone="bold" className={`border ${style}`}>
      {value || "?"}
    </Chip>
  );
}

function RiskBadge({ risk }: { risk: string }) {
  const cfg = RISK_STYLE[risk] ?? RISK_STYLE.LOW;
  const Icon = cfg.icon;
  return (
    <div className={`flex items-center gap-1 text-[length:var(--t-2xs)] font-semibold ${cfg.bg}`}>
      <Icon size={10} />
      {risk}
    </div>
  );
}

function TrendIndicator({ trend, momentum }: { trend: string; momentum: string }) {
  const color = TREND_STYLE[trend] ?? "text-slate-500";
  const mom = numeric(momentum);
  const Icon = mom >= 0 ? TrendingUp : TrendingDown;
  if (!trend || trend === "?") return null;
  return (
    <div className={`flex items-center gap-1 text-[length:var(--t-2xs)] ${color}`}>
      <Icon size={10} />
      <span className="font-medium">{mom >= 0 ? "+" : ""}{mom.toFixed(1)}%</span>
      <span className="text-slate-600">5d</span>
    </div>
  );
}

function ConfidenceGauge({ value }: { value: number }) {
  // Circular ring showing 0-100%. Red >= 60, Amber 30-60, Green < 30.
  const radius = 14;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.min(100, Math.max(0, value));
  const offset = circumference * (1 - progress / 100);

  const color = value >= 60 ? "#ef4444" : value >= 30 ? "#f59e0b" : "#10b981";

  return (
    <div className="relative flex items-center justify-center" style={{ width: 36, height: 36 }}>
      <svg width="36" height="36" className="rotate-[-90deg]">
        <circle cx="18" cy="18" r={radius} stroke="rgba(255,255,255,0.08)" strokeWidth="3" fill="none" />
        <circle
          cx="18" cy="18" r={radius}
          stroke={color} strokeWidth="3" fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
      </svg>
      <span className="absolute text-[length:var(--t-2xs)] font-bold tabular-nums" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

function scoreColor(score: number): string {
  if (score >= 30) return "text-emerald-400";
  if (score <= -30) return "text-red-400";
  return "text-slate-400";
}

function OptionItem({
  opt,
  stockPositions,
  techScore,
  exitPlan,
  defense,
}: {
  opt: OptionRow;
  stockPositions: PositionRow[];
  techScore?: TechnicalScoreRow;
  exitPlan?: ExitPlanRow;
  defense?: OptionsDefenseRow;
}) {
  const [expanded, setExpanded] = useState(false);
  const right = opt.right === "C" ? "CALL" : opt.right === "P" ? "PUT" : opt.right;
  const dte = numeric(opt.dte);
  const dteLabel = dte < 0 ? "—" : dte === 0 ? "EXP" : `${dte}d`;
  const adjCost = numeric(opt.adj_cost_basis);
  const underlying = numeric(opt.underlying_last);
  const strike = numeric(opt.strike);
  const wheelLeg = WHEEL_LEG_LABEL[opt.wheel_leg] ?? opt.wheel_leg;
  const confidence = numeric(opt.confidence_pct);
  const vol = numeric(opt.volatility_annual) * 100;
  const rsi = numeric(opt.rsi_14);
  const sma20 = numeric(opt.sma_20);
  const sma50 = numeric(opt.sma_50);

  // Find matching stock position for context
  const stock = stockPositions.find((p) => p.ticker === opt.ticker);
  const stockQty = stock ? numeric(stock.qty) : 0;
  const stockAvg = stock ? numeric(stock.avg_cost) : 0;

  // Short premium row (negative contracts) → wheel-mechanics strip applies.
  const isShort = numeric(opt.qty) < 0;

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className="w-full text-left glass rounded-xl p-3.5 space-y-2.5 active:bg-white/3 transition-colors"
    >
      {/* Header: ticker + strike + moneyness + confidence */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{opt.ticker}</span>
          <span className="text-[length:var(--t-2xs)] font-semibold text-slate-500 shrink-0">
            {fmtStrike(opt.strike)} {right}
          </span>
          <MoneynessChip value={opt.moneyness} />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex flex-col items-end leading-tight">
            {/* 21d-rule thresholds (shared with OptionMechanics): red ≤7, amber ≤21.
                Previously ambered only at ≤7 — two weeks past the act point. */}
            <span className={`text-[length:var(--t-2xs)] font-mono tabular-nums ${dte >= 0 ? dteClass(dte) : "text-slate-500"}`}>
              {dteLabel}
            </span>
            <span className="text-[length:var(--t-2xs)] text-slate-600">exp {fmtExp(opt.expiry)}</span>
          </div>
          <ConfidenceGauge value={confidence} />
        </div>
      </div>

      {/* Wheel leg + shares + risk/trend */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-2xs)] font-medium text-indigo-400">{wheelLeg}</span>
          {stockQty > 0 && (
            <span className="text-[length:var(--t-2xs)] text-slate-600">
              {stockQty} @ {fmtPrice(stockAvg)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <TrendIndicator trend={opt.trend_risk} momentum={opt.momentum_5d} />
          <RiskBadge risk={opt.assignment_risk} />
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center flex-wrap gap-x-4 gap-y-1 text-[length:var(--t-2xs)] text-slate-500">
        <span>Stock: <span className="text-slate-300 tabular-nums">{fmtPrice(underlying)}</span></span>
        {strike > 0 && !isShort && (
          <span>
            Dist: <span className={`tabular-nums ${
              opt.moneyness === "ITM" ? "text-red-400" : "text-emerald-400"
            }`}>
              {underlying > 0 ? `${(((underlying - strike) / strike) * 100).toFixed(1)}%` : "—"}
            </span>
          </span>
        )}
        <span>Credit: <span className="text-slate-300 tabular-nums">{fmtPrice(opt.credit)}</span></span>
        {adjCost > 0 && (
          <span>Adj basis: <span className="text-cyan-400 tabular-nums">{fmtPrice(adjCost)}</span></span>
        )}
      </div>

      {/* Wheel mechanics strip — captured% / 21d rule / distance-to-strike /
          max loss, computed from the row's own fields (UI audit #3). */}
      {isShort && (
        <OptionMechanics
          credit={numOrUndef(opt.credit)}
          last={numOrUndef(opt.last)}
          dte={dte >= 0 ? dte : undefined}
          strike={numOrUndef(opt.strike)}
          underlying={numOrUndef(opt.underlying_last)}
          right={opt.right}
          qty={numOrUndef(opt.qty)}
          leg={opt.wheel_leg}
        />
      )}

      {/* Inline defense join — a HIGH-assignment / BREACHING row prints its
          matching Daily Defense action here instead of requiring the manual
          ticker+strike join one subtab away. */}
      {defense && (
        <div className="flex items-start gap-1.5 text-[length:var(--t-2xs)] pt-1.5 border-t border-white/5">
          <Shield size={10} className={`shrink-0 mt-0.5 ${defense.severity === "CRITICAL" ? "text-red-400" : "text-orange-400"}`} />
          <span className="text-slate-500 shrink-0">Defense:</span>
          <span className={`font-medium leading-snug ${defense.severity === "CRITICAL" ? "text-red-400" : "text-orange-400"}`}>
            {defense.action}
          </span>
        </div>
      )}

      {/* Sell calls above indicator */}
      {adjCost > 0 && opt.wheel_leg === "CC" && (
        <div className="flex items-center gap-1.5 text-[length:var(--t-2xs)]">
          <Shield size={10} className="text-cyan-400" />
          <span className="text-slate-500">Sell calls above</span>
          <span className="text-cyan-400 font-semibold tabular-nums">{fmtPrice(adjCost)}</span>
          {strike > 0 && adjCost > 0 && (
            <span className={`ml-1 ${strike >= adjCost ? "text-emerald-400" : "text-red-400"}`}>
              {strike >= adjCost ? "safe" : "below basis!"}
            </span>
          )}
        </div>
      )}

      {/* Exit plan target — captured% now comes from the mechanics strip above
          (computed from the row's own credit/last, so it renders even when no
          fresh exit-plan row matches); keep the plan's close target when one exists. */}
      {exitPlan && numeric(exitPlan.target_close_at) > 0 && (
        <div className="flex items-center gap-1.5 text-[length:var(--t-2xs)] pt-1.5 border-t border-white/5">
          <Shield size={10} className="text-indigo-400" />
          <span className="text-slate-500">Close at</span>
          <span className="text-emerald-400 font-semibold tabular-nums">${numeric(exitPlan.target_close_at).toFixed(2)}</span>
        </div>
      )}

      {/* Expanded: confidence reasoning + indicator table + tech scores */}
      {expanded && (
        <div className="pt-2.5 border-t border-white/5 space-y-2">
          <div className="flex items-start gap-1.5">
            <Info size={10} className="text-slate-500 mt-0.5 shrink-0" />
            <p className="text-[length:var(--t-2xs)] text-slate-400 leading-relaxed">
              {opt.confidence_reasoning || "No reasoning available"}
            </p>
          </div>

          {/* Strategy scores for this ticker */}
          {techScore && (
            <div className="pt-1.5 border-t border-white/5">
              <div className="text-[length:var(--t-2xs)] text-slate-600 mb-1">Strategy scores</div>
              <div className="grid grid-cols-5 gap-1.5 text-[length:var(--t-2xs)]">
                {[
                  { label: "BUY", val: numeric(techScore.score_buy) },
                  { label: "CSP", val: numeric(techScore.score_csp) },
                  { label: "CC", val: numeric(techScore.score_cc) },
                  { label: "LC", val: numeric(techScore.score_long_call) },
                  { label: "LP", val: numeric(techScore.score_long_put) },
                ].map((s) => (
                  <div key={s.label} className="text-center">
                    <div className="text-slate-600">{s.label}</div>
                    <div className={`tabular-nums font-semibold ${scoreColor(s.val)}`}>
                      {s.val > 0 ? "+" : ""}{s.val.toFixed(0)}
                    </div>
                  </div>
                ))}
              </div>
              {techScore.top_drivers && (
                <div className="text-[length:var(--t-2xs)] text-slate-500 mt-1.5 leading-relaxed">
                  {techScore.top_drivers}
                </div>
              )}
              {techScore.earnings_date && numeric(techScore.earnings_days_away) >= 0 && (
                <div className={`flex items-center gap-1 text-[length:var(--t-2xs)] mt-1.5 ${
                  numeric(techScore.earnings_days_away) <= 7 ? "text-red-400" :
                  numeric(techScore.earnings_days_away) <= 14 ? "text-amber-400" : "text-slate-400"
                }`}>
                  <Zap size={10} />
                  <span className="font-semibold">
                    Earnings {techScore.earnings_date} ({techScore.earnings_days_away}d away)
                  </span>
                </div>
              )}
              {techScore.catalyst_flag === "TRUE" && !techScore.earnings_date && (
                <div className="flex items-center gap-1 text-[length:var(--t-2xs)] text-orange-400 mt-1.5">
                  <Zap size={10} />
                  <span className="font-semibold">Catalyst detected — elevated vol regime</span>
                </div>
              )}
            </div>
          )}

          {/* Indicator table */}
          <div className="grid grid-cols-4 gap-1.5 text-[length:var(--t-2xs)] pt-1.5 border-t border-white/5">
            <div>
              <div className="text-slate-600">Vol (σ)</div>
              <div className="tabular-nums text-slate-300">{vol > 0 ? `${vol.toFixed(0)}%` : "—"}</div>
            </div>
            <div>
              <div className="text-slate-600">RSI(14)</div>
              <div className={`tabular-nums ${rsi > 70 ? "text-red-400" : rsi < 30 ? "text-amber-400" : "text-slate-300"}`}>
                {rsi > 0 ? rsi.toFixed(0) : "—"}
              </div>
            </div>
            <div>
              <div className="text-slate-600">SMA20</div>
              <div className="tabular-nums text-slate-300">{sma20 > 0 ? fmtPrice(sma20) : "—"}</div>
            </div>
            <div>
              <div className="text-slate-600">SMA50</div>
              <div className="tabular-nums text-slate-300">{sma50 > 0 ? fmtPrice(sma50) : "—"}</div>
            </div>
          </div>
        </div>
      )}
    </button>
  );
}

// ---------- main card ----------

export function WheelCard({
  options,
  casparPositions,
  sarahPositions,
  technicalScores,
  exitPlans,
  optionsDefense,
  loading,
}: {
  options: OptionRow[];
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  technicalScores?: TechnicalScoreRow[];
  exitPlans?: ExitPlanRow[];
  optionsDefense?: OptionsDefenseRow[];
  loading?: boolean;
}) {
  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) {
    techByTicker.set(t.ticker, t);
  }
  // Option exit plans grouped by account|ticker. The old single-key map
  // collided when one ticker carried both a CSP and a CC, attaching the wrong
  // plan; ExitPlanRow carries no strike/right/expiry, so disambiguate by
  // position_type (OPTION_CSP vs OPTION_CC) and only fall back to a loose
  // match when the ticker has exactly ONE option plan.
  const optionPlans = new Map<string, ExitPlanRow[]>();
  for (const e of exitPlans ?? []) {
    if (!e.position_type?.startsWith("OPTION")) continue;
    const k = `${e.account}|${e.ticker}`;
    const arr = optionPlans.get(k) ?? [];
    arr.push(e);
    optionPlans.set(k, arr);
  }
  const planFor = (opt: OptionRow): ExitPlanRow | undefined => {
    const list = optionPlans.get(`${opt.account}|${opt.ticker}`);
    if (!list?.length) return undefined;
    const want = opt.wheel_leg === "CSP" ? "OPTION_CSP" : opt.wheel_leg === "CC" ? "OPTION_CC" : "";
    return list.find((e) => e.position_type === want) ?? (list.length === 1 ? list[0] : undefined);
  };
  // Defense join: only rows the mechanics flag as in trouble get the inline
  // action (assignment_risk HIGH or trend_risk BREACHING), matched by
  // account + ticker + right + strike.
  const defenseFor = (opt: OptionRow): OptionsDefenseRow | undefined => {
    if (opt.assignment_risk !== "HIGH" && opt.trend_risk !== "BREACHING") return undefined;
    return (optionsDefense ?? []).find(
      (d) =>
        d.ticker === opt.ticker &&
        d.account === opt.account &&
        (!d.right || d.right === opt.right) &&
        Math.abs(numeric(d.strike) - numeric(opt.strike)) < 0.5 &&
        !!d.action,
    );
  };
  if (loading) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <div className="shimmer h-4 w-24" />
        </div>
        <div className="space-y-2">
          <div className="shimmer h-20 w-full rounded-xl" />
          <div className="shimmer h-20 w-full rounded-xl" />
        </div>
      </Card>
    );
  }

  if (!options.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <CircleDot size={16} />
          <span className="text-[length:var(--t-sm)]">Options / Wheel -- no positions</span>
        </div>
      </Card>
    );
  }

  // Group by account
  const byAccount: Record<string, OptionRow[]> = {};
  for (const o of options) {
    (byAccount[o.account] ??= []).push(o);
  }

  // Count risk levels
  const highRisk = options.filter((o) => o.assignment_risk === "HIGH").length;
  const medRisk = options.filter((o) => o.assignment_risk === "MED").length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <CircleDot size={14} className="text-indigo-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Options & Wheel</h2>
        </div>
        <div className="flex items-center gap-2">
          {highRisk > 0 && (
            <Chip pad="md" tone="bold" className="border bg-red-500/15 text-red-400 border-red-500/20">
              {highRisk} HIGH
            </Chip>
          )}
          {medRisk > 0 && (
            <Chip pad="md" tone="bold" className="border bg-amber-500/15 text-amber-400 border-amber-500/20">
              {medRisk} MED
            </Chip>
          )}
          <span className="text-[length:var(--t-2xs)] text-slate-600">{options.length} positions</span>
        </div>
      </div>

      <div className="space-y-3">
        {Object.entries(byAccount).map(([acct, opts]) => (
          <div key={acct}>
            <div className={`text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider mb-1.5 ${
              acct === "caspar" ? "text-blue-400" : "text-pink-400"
            }`}>
              {acct === "caspar" ? "Caspar" : "Sarah"}
            </div>
            <div className="space-y-2">
              {opts.map((opt, i) => (
                <OptionItem
                  key={`${opt.ticker}-${opt.strike}-${opt.right}-${i}`}
                  opt={opt}
                  stockPositions={acct === "caspar" ? casparPositions : sarahPositions}
                  techScore={techByTicker.get(opt.ticker)}
                  exitPlan={planFor(opt)}
                  defense={defenseFor(opt)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
