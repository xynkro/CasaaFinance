import type { OptionRow, PositionRow } from "../data";
import { Card } from "./Card";
import { CircleDot, AlertTriangle, TrendingUp, TrendingDown, Shield } from "lucide-react";

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
    <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${style}`}>
      {value || "?"}
    </span>
  );
}

function RiskBadge({ risk }: { risk: string }) {
  const cfg = RISK_STYLE[risk] ?? RISK_STYLE.LOW;
  const Icon = cfg.icon;
  return (
    <div className={`flex items-center gap-1 text-[10px] font-semibold ${cfg.bg}`}>
      <Icon size={10} />
      {risk}
    </div>
  );
}

function TrendIndicator({ trend, momentum }: { trend: string; momentum: string }) {
  const color = TREND_STYLE[trend] ?? "text-slate-500";
  const mom = Number(momentum);
  const Icon = mom >= 0 ? TrendingUp : TrendingDown;
  if (!trend || trend === "?") return null;
  return (
    <div className={`flex items-center gap-1 text-[10px] ${color}`}>
      <Icon size={10} />
      <span className="font-medium">{mom >= 0 ? "+" : ""}{mom.toFixed(1)}%</span>
      <span className="text-slate-600">5d</span>
    </div>
  );
}

function OptionItem({ opt, stockPositions }: { opt: OptionRow; stockPositions: PositionRow[] }) {
  const right = opt.right === "C" ? "CALL" : opt.right === "P" ? "PUT" : opt.right;
  const dte = Number(opt.dte);
  const dteLabel = dte < 0 ? "—" : dte === 0 ? "EXP" : `${dte}d`;
  const adjCost = Number(opt.adj_cost_basis);
  const underlying = Number(opt.underlying_last);
  const strike = Number(opt.strike);
  const wheelLeg = WHEEL_LEG_LABEL[opt.wheel_leg] ?? opt.wheel_leg;

  // Find matching stock position for context
  const stock = stockPositions.find((p) => p.ticker === opt.ticker);
  const stockQty = stock ? Number(stock.qty) : 0;
  const stockAvg = stock ? Number(stock.avg_cost) : 0;

  return (
    <div className="glass rounded-xl p-3.5 space-y-2.5">
      {/* Header: ticker + type + moneyness */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-white">{opt.ticker}</span>
          <span className="text-[10px] font-semibold text-slate-500">
            {fmtStrike(opt.strike)} {right}
          </span>
          <MoneynessChip value={opt.moneyness} />
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-mono tabular-nums ${dte <= 7 && dte >= 0 ? "text-amber-400 font-bold" : "text-slate-500"}`}>
            {dteLabel}
          </span>
          <span className="text-[10px] text-slate-600">exp {fmtExp(opt.expiry)}</span>
        </div>
      </div>

      {/* Wheel leg + risk + trend */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium text-indigo-400">{wheelLeg}</span>
          {stockQty > 0 && (
            <span className="text-[10px] text-slate-600">
              {stockQty} shares @ {fmtPrice(stockAvg)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <TrendIndicator trend={opt.trend_risk} momentum={opt.momentum_5d} />
          <RiskBadge risk={opt.assignment_risk} />
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-[10px] text-slate-500">
        <span>Underlying: <span className="text-slate-300 tabular-nums">{fmtPrice(underlying)}</span></span>
        {strike > 0 && (
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

      {/* Sell calls above indicator */}
      {adjCost > 0 && opt.wheel_leg === "CC" && (
        <div className="flex items-center gap-1.5 text-[10px]">
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
    </div>
  );
}

// ---------- main card ----------

export function WheelCard({
  options,
  casparPositions,
  sarahPositions,
  loading,
}: {
  options: OptionRow[];
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  loading?: boolean;
}) {
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
          <span className="text-sm">Options / Wheel -- no positions</span>
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
          <h2 className="text-sm font-medium text-slate-400">Options & Wheel</h2>
        </div>
        <div className="flex items-center gap-2">
          {highRisk > 0 && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-400 border border-red-500/20">
              {highRisk} HIGH
            </span>
          )}
          {medRisk > 0 && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/20">
              {medRisk} MED
            </span>
          )}
          <span className="text-[10px] text-slate-600">{options.length} positions</span>
        </div>
      </div>

      <div className="space-y-2">
        {Object.entries(byAccount).map(([acct, opts]) => (
          <div key={acct}>
            {Object.keys(byAccount).length > 1 && (
              <div className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider mb-1.5">
                {acct}
              </div>
            )}
            <div className="space-y-2">
              {opts.map((opt, i) => (
                <OptionItem
                  key={`${opt.ticker}-${opt.strike}-${opt.right}-${i}`}
                  opt={opt}
                  stockPositions={acct === "caspar" ? casparPositions : sarahPositions}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
