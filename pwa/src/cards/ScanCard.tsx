import type { ScanResultRow, OptionRecommendationRow } from "../data";
import { Card } from "./Card";
import { Radar, Zap, TrendingUp, TrendingDown } from "lucide-react";
import { useState } from "react";

function fmtPrice(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toFixed(2)}`;
}

function fmtExp(exp: string): string {
  // scan_results uses "YYYYMMDD"; option_recommendations uses "YYYY-MM-DD"
  if (!exp) return "—";
  if (exp.length === 8 && !exp.includes("-")) {
    return `${exp.slice(4, 6)}/${exp.slice(6, 8)}`;
  }
  if (exp.length >= 10 && exp[4] === "-" && exp[7] === "-") {
    return `${exp.slice(5, 7)}/${exp.slice(8, 10)}`;
  }
  return exp;
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
      <span className="absolute text-[length:var(--t-2xs)] font-bold tabular-nums" style={{ color }}>
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
          <span className="text-[length:var(--t-sm)] font-bold text-white">{cand.ticker}</span>
          <span className="text-[length:var(--t-2xs)] font-semibold text-slate-500">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{cand.right}
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-600">exp {fmtExp(cand.expiry)}</span>
          {catalyst && (
            <Zap size={10} className="text-orange-400 shrink-0" />
          )}
        </div>
        <CompositeGauge value={composite} />
      </div>

      {/* Key metrics */}
      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500">
        <span>Δ <span className="text-slate-300 tabular-nums">{delta.toFixed(2)}</span></span>
        <span>Prem <span className="text-slate-300 tabular-nums">{fmtPrice(prem)}</span></span>
        <span>Yield <span className="text-emerald-400 tabular-nums font-semibold">{yld.toFixed(0)}%</span></span>
        <span>Cash <span className="text-slate-300 tabular-nums">{fmtPrice(cash)}</span></span>
      </div>

      {expanded && (
        <div className="pt-2 border-t border-white/5 space-y-2 text-[length:var(--t-2xs)]">
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
          <div className="text-[length:var(--t-2xs)] text-slate-500">
            Stock: <span className="text-slate-300 tabular-nums">{fmtPrice(cand.underlying_last)}</span>
          </div>
          {catalyst && (
            <div className="flex items-center gap-1 text-orange-400 text-[length:var(--t-2xs)]">
              <Zap size={10} />
              <span className="font-semibold">Catalyst — volatility elevated</span>
            </div>
          )}
        </div>
      )}
    </button>
  );
}

/** Slimmer card variant for option_recommendations (market_scan source).
 * Schema is partial: no composite_score, technical_score, iv_rank-context, dte, bid/ask.
 * Fields rendered: ticker, strike, right, expiry, premium, delta, yield, cash,
 * breakeven, iv_rank, thesis_confidence, thesis. */
function BroadCandidateItem({ cand }: { cand: OptionRecommendationRow }) {
  const [expanded, setExpanded] = useState(false);
  const strike = Number(cand.strike);
  const delta = Number(cand.delta);
  const prem = Number(cand.premium_per_share);
  const yld = Number(cand.annual_yield_pct);
  const cash = Number(cand.cash_required);
  const ivRank = Number(cand.iv_rank);
  const conf = Number(cand.thesis_confidence);
  const isCall = cand.right === "C";
  const isPut = cand.right === "P";
  const hasRight = isCall || isPut;

  // Confidence is 0-1, scale to 0-100 for the gauge
  const confPct = isNaN(conf) ? 0 : conf * 100;

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className="w-full text-left glass rounded-xl p-3 active:bg-white/3 transition-colors space-y-2"
    >
      {/* Top row: ticker + strategy + strike + confidence ring */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {hasRight && (isCall ? (
            <TrendingDown size={11} className="text-amber-400 shrink-0" />
          ) : (
            <TrendingUp size={11} className="text-emerald-400 shrink-0" />
          ))}
          <span className="text-[length:var(--t-sm)] font-bold text-white">{cand.ticker}</span>
          <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wide text-indigo-300">
            {cand.strategy}
          </span>
          {hasRight && !isNaN(strike) && (
            <span className="text-[length:var(--t-2xs)] font-semibold text-slate-500">
              ${strike.toFixed(strike < 10 ? 1 : 0)}{cand.right}
            </span>
          )}
          {cand.expiry && (
            <span className="text-[length:var(--t-2xs)] text-slate-600">exp {fmtExp(cand.expiry)}</span>
          )}
        </div>
        {!isNaN(conf) && conf > 0 && <CompositeGauge value={confPct} />}
      </div>

      {/* Key metrics */}
      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500">
        <span>Δ <span className="text-slate-300 tabular-nums">{isNaN(delta) ? "—" : delta.toFixed(2)}</span></span>
        <span>Prem <span className="text-slate-300 tabular-nums">{isNaN(prem) ? "—" : fmtPrice(prem)}</span></span>
        <span>Yield <span className="text-emerald-400 tabular-nums font-semibold">{isNaN(yld) ? "—" : `${yld.toFixed(0)}%`}</span></span>
        <span>Cash <span className="text-slate-300 tabular-nums">{isNaN(cash) ? "—" : fmtPrice(cash)}</span></span>
      </div>

      {expanded && (
        <div className="pt-2 border-t border-white/5 space-y-2 text-[length:var(--t-2xs)]">
          <div className="grid grid-cols-3 gap-1.5">
            <div>
              <div className="text-slate-600">BE</div>
              <div className="tabular-nums text-slate-300">{cand.breakeven ? fmtPrice(cand.breakeven) : "—"}</div>
            </div>
            <div>
              <div className="text-slate-600">IVR</div>
              <div className={`tabular-nums font-semibold ${
                ivRank >= 60 ? "text-emerald-400" : ivRank >= 40 ? "text-amber-400" : "text-slate-400"
              }`}>
                {isNaN(ivRank) ? "—" : ivRank.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-slate-600">Conf</div>
              <div className="tabular-nums text-slate-300">{isNaN(conf) ? "—" : `${(conf * 100).toFixed(0)}%`}</div>
            </div>
          </div>
          {cand.thesis && (
            <div className="text-[length:var(--t-2xs)] text-slate-400 leading-relaxed">
              {cand.thesis}
            </div>
          )}
          <div className="text-[length:var(--t-2xs)] text-slate-600">
            <span className="uppercase">{cand.account || "—"}</span>
            {cand.status && <span> · {cand.status}</span>}
          </div>
        </div>
      )}
    </button>
  );
}

type Source = "my-tickers" | "broad";
type StratTab = "CSP" | "CC";

export function ScanCard({
  candidates,
  broadCandidates,
}: {
  candidates: ScanResultRow[];
  broadCandidates?: OptionRecommendationRow[];
}) {
  const [source, setSource] = useState<Source>("my-tickers");
  const [tab, setTab] = useState<StratTab>("CSP");

  const broad = broadCandidates ?? [];

  // ----- "My Tickers" lists (unchanged behavior) -----
  const cspList = candidates
    .filter((c) => c.strategy === "CSP")
    .sort((a, b) => Number(b.composite_score) - Number(a.composite_score))
    .slice(0, 8);
  const ccList = candidates
    .filter((c) => c.strategy === "CC")
    .sort((a, b) => Number(b.composite_score) - Number(a.composite_score))
    .slice(0, 8);

  // ----- "Broad" lists -----
  // market_scan produces multiple strategies; we still split by CSP/CC for the
  // strategy pill but show all broad candidates that match the active strategy.
  // Sort by thesis_confidence desc, then yield.
  const broadSort = (a: OptionRecommendationRow, b: OptionRecommendationRow) => {
    const cd = Number(b.thesis_confidence) - Number(a.thesis_confidence);
    if (!isNaN(cd) && cd !== 0) return cd;
    return Number(b.annual_yield_pct) - Number(a.annual_yield_pct);
  };
  const broadCsp = broad.filter((c) => c.strategy === "CSP").sort(broadSort).slice(0, 12);
  const broadCc = broad.filter((c) => c.strategy === "CC").sort(broadSort).slice(0, 12);

  const myActive = tab === "CSP" ? cspList : ccList;
  const broadActive = tab === "CSP" ? broadCsp : broadCc;

  const onMyTickers = source === "my-tickers";
  const empty =
    (onMyTickers && !candidates.length) ||
    (!onMyTickers && !broad.length);

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radar size={14} className="text-indigo-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Daily Scan</h2>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setTab("CSP")}
            className={`px-2.5 py-1 rounded-md text-[length:var(--t-2xs)] font-semibold transition-all ${
              tab === "CSP"
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                : "text-slate-500 hover:text-slate-300 border border-transparent"
            }`}
          >
            CSP ({onMyTickers ? cspList.length : broadCsp.length})
          </button>
          <button
            onClick={() => setTab("CC")}
            className={`px-2.5 py-1 rounded-md text-[length:var(--t-2xs)] font-semibold transition-all ${
              tab === "CC"
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                : "text-slate-500 hover:text-slate-300 border border-transparent"
            }`}
          >
            CC ({onMyTickers ? ccList.length : broadCc.length})
          </button>
        </div>
      </div>

      {/* Source pill row */}
      <div className="flex items-center gap-1 mb-3">
        <button
          onClick={() => setSource("my-tickers")}
          className={`px-2.5 py-1 rounded-md text-[length:var(--t-2xs)] font-semibold transition-all ${
            onMyTickers
              ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
              : "text-slate-500 hover:text-slate-300 border border-transparent"
          }`}
        >
          My Tickers ({candidates.length})
        </button>
        <button
          onClick={() => setSource("broad")}
          className={`px-2.5 py-1 rounded-md text-[length:var(--t-2xs)] font-semibold transition-all ${
            !onMyTickers
              ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
              : "text-slate-500 hover:text-slate-300 border border-transparent"
          }`}
        >
          Broad ({broad.length})
        </button>
      </div>

      {empty ? (
        <div className="flex items-center gap-2 text-slate-500">
          <Radar size={16} />
          <span className="text-[length:var(--t-sm)]">
            {onMyTickers
              ? "No candidates in My Tickers (market closed?)"
              : "No Broad candidates yet"}
          </span>
        </div>
      ) : (
        <>
          <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
            {onMyTickers
              ? "My Tickers — composite = 40% technical + 25% yield + 20% IV rank + 10% cash eff + 5% liquidity."
              : "Broad — LunarCrush trending + WSB + quality watchlist (sorted by thesis confidence)."}
          </p>

          <div className="space-y-2">
            {onMyTickers
              ? myActive.map((c, i) => (
                  <CandidateItem key={`mt-${c.ticker}-${c.strike}-${c.right}-${i}`} cand={c} />
                ))
              : broadActive.map((c, i) => (
                  <BroadCandidateItem key={`br-${c.ticker}-${c.strike}-${c.right}-${i}`} cand={c} />
                ))}
          </div>
        </>
      )}
    </Card>
  );
}
