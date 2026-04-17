import type { ScanResultRow } from "../data";
import { Card } from "./Card";
import { Radar, Zap, TrendingUp, TrendingDown } from "lucide-react";
import { useState } from "react";

function fmtPrice(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toFixed(2)}`;
}

function fmtExp(exp: string): string {
  if (!exp || exp.length !== 8) return exp;
  return `${exp.slice(4, 6)}/${exp.slice(6, 8)}`;
}

function CompositeGauge({ value }: { value: number }) {
  const radius = 12;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(100, value));
  const offset = circumference * (1 - progress / 100);
  const color = value >= 55 ? "#10b981" : value >= 40 ? "#f59e0b" : "#64748b";

  return (
    <div className="relative flex items-center justify-center" style={{ width: 32, height: 32 }}>
      <svg width="32" height="32" className="rotate-[-90deg]">
        <circle cx="16" cy="16" r={radius} stroke="rgba(255,255,255,0.08)" strokeWidth="2.5" fill="none" />
        <circle
          cx="16" cy="16" r={radius}
          stroke={color} strokeWidth="2.5" fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
      </svg>
      <span className="absolute text-[9px] font-bold tabular-nums" style={{ color }}>
        {Math.round(value)}
      </span>
    </div>
  );
}

function CandidateItem({ cand }: { cand: ScanResultRow }) {
  const [expanded, setExpanded] = useState(false);
  const strike = Number(cand.strike);
  const delta = Number(cand.delta);
  const prem = Number(cand.premium);
  const yld = Number(cand.annual_yield_pct);
  const cash = Number(cand.cash_required);
  const ivRank = Number(cand.iv_rank);
  const techScore = Number(cand.technical_score);
  const composite = Number(cand.composite_score);
  const catalyst = cand.catalyst_flag === "TRUE";
  const isCall = cand.right === "C";

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className="w-full text-left glass rounded-xl p-3 active:bg-white/3 transition-colors space-y-2"
    >
      {/* Top row: ticker + strike + composite ring */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isCall ? (
            <TrendingDown size={11} className="text-amber-400 shrink-0" />
          ) : (
            <TrendingUp size={11} className="text-emerald-400 shrink-0" />
          )}
          <span className="text-sm font-bold text-white">{cand.ticker}</span>
          <span className="text-[10px] font-semibold text-slate-500">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{cand.right}
          </span>
          <span className="text-[9px] text-slate-600">exp {fmtExp(cand.expiry)}</span>
          {catalyst && (
            <Zap size={10} className="text-orange-400 shrink-0" />
          )}
        </div>
        <CompositeGauge value={composite} />
      </div>

      {/* Key metrics */}
      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
        <span>Δ <span className="text-slate-300 tabular-nums">{delta.toFixed(2)}</span></span>
        <span>Prem <span className="text-slate-300 tabular-nums">{fmtPrice(prem)}</span></span>
        <span>Yield <span className="text-emerald-400 tabular-nums font-semibold">{yld.toFixed(0)}%</span></span>
        <span>Cash <span className="text-slate-300 tabular-nums">{fmtPrice(cash)}</span></span>
      </div>

      {expanded && (
        <div className="pt-2 border-t border-white/5 space-y-2 text-[10px]">
          <div className="grid grid-cols-4 gap-1.5">
            <div>
              <div className="text-slate-600">BE</div>
              <div className="tabular-nums text-slate-300">{fmtPrice(cand.breakeven)}</div>
            </div>
            <div>
              <div className="text-slate-600">IV</div>
              <div className="tabular-nums text-slate-300">{(Number(cand.iv) * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div className="text-slate-600">IVR</div>
              <div className={`tabular-nums font-semibold ${
                ivRank >= 60 ? "text-emerald-400" : ivRank >= 40 ? "text-amber-400" : "text-slate-400"
              }`}>
                {ivRank.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-slate-600">Spread</div>
              <div className="tabular-nums text-slate-300">{Number(cand.spread_pct).toFixed(1)}%</div>
            </div>
            <div>
              <div className="text-slate-600">Tech</div>
              <div className={`tabular-nums font-semibold ${
                techScore >= 30 ? "text-emerald-400" : techScore <= -30 ? "text-red-400" : "text-slate-400"
              }`}>
                {techScore > 0 ? "+" : ""}{techScore.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-slate-600">DTE</div>
              <div className="tabular-nums text-slate-300">{cand.dte}d</div>
            </div>
            <div>
              <div className="text-slate-600">Bid</div>
              <div className="tabular-nums text-slate-300">{fmtPrice(cand.bid)}</div>
            </div>
            <div>
              <div className="text-slate-600">Ask</div>
              <div className="tabular-nums text-slate-300">{fmtPrice(cand.ask)}</div>
            </div>
          </div>
          <div className="text-[10px] text-slate-500">
            Stock: <span className="text-slate-300 tabular-nums">{fmtPrice(cand.underlying_last)}</span>
          </div>
          {catalyst && (
            <div className="flex items-center gap-1 text-orange-400 text-[10px]">
              <Zap size={10} />
              <span className="font-semibold">Catalyst — volatility elevated</span>
            </div>
          )}
        </div>
      )}
    </button>
  );
}

export function ScanCard({ candidates }: { candidates: ScanResultRow[] }) {
  const [tab, setTab] = useState<"CSP" | "CC">("CSP");

  if (!candidates.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Radar size={16} />
          <span className="text-sm">Scanner — no candidates (market closed?)</span>
        </div>
      </Card>
    );
  }

  const cspList = candidates
    .filter((c) => c.strategy === "CSP")
    .sort((a, b) => Number(b.composite_score) - Number(a.composite_score))
    .slice(0, 8);
  const ccList = candidates
    .filter((c) => c.strategy === "CC")
    .sort((a, b) => Number(b.composite_score) - Number(a.composite_score))
    .slice(0, 8);

  const active = tab === "CSP" ? cspList : ccList;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radar size={14} className="text-indigo-400" />
          <h2 className="text-sm font-medium text-slate-400">Daily Scan</h2>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setTab("CSP")}
            className={`px-2.5 py-1 rounded-md text-[10px] font-semibold transition-all ${
              tab === "CSP"
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                : "text-slate-500 hover:text-slate-300 border border-transparent"
            }`}
          >
            CSP ({cspList.length})
          </button>
          <button
            onClick={() => setTab("CC")}
            className={`px-2.5 py-1 rounded-md text-[10px] font-semibold transition-all ${
              tab === "CC"
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                : "text-slate-500 hover:text-slate-300 border border-transparent"
            }`}
          >
            CC ({ccList.length})
          </button>
        </div>
      </div>

      <p className="text-[10px] text-slate-600 mb-3 leading-relaxed">
        Ranked by composite = 40% technical score + 25% yield + 20% IV rank + 10% cash eff + 5% liquidity.
      </p>

      <div className="space-y-2">
        {active.map((c, i) => (
          <CandidateItem key={`${c.ticker}-${c.strike}-${c.right}-${i}`} cand={c} />
        ))}
      </div>
    </Card>
  );
}
