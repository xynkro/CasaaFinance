import type { ScanResultRow, OptionRecommendationRow } from "../data";
import { Card } from "./Card";
import { Radar, Zap, TrendingUp, TrendingDown, Rocket } from "lucide-react";
import { useState } from "react";

// ── 3-phase management rules (tastytrade) ────────────────────
const MGMT_RULES: Record<string, { entry: string; manage: string; exit: string }> = {
  CSP:       { entry: "35 DTE · 20-30Δ · yield ≥12%",       manage: "Close at 50% profit · roll down+out if tested",          exit: "50% profit OR assignment → wheel into CC" },
  CC:        { entry: "35 DTE · 10-20Δ · yield ≥10%",       manage: "Close at 50% profit · let ride if far OTM",              exit: "50% profit OR assignment → wheel into CSP" },
  PCS:       { entry: "42 DTE · 25Δ · credit ≥⅓ width",     manage: "Close at 50% profit · roll if short tested",             exit: "50% profit OR 21 DTE mech close · stop 2× credit" },
  CCS:       { entry: "42 DTE · 25Δ · credit ≥⅓ width",     manage: "Close at 50% profit · roll if short tested",             exit: "50% profit OR 21 DTE mech close · stop 2× credit" },
  IC:        { entry: "45 DTE · 20Δ shorts · cr/w ≥30%",    manage: "Close at 50% profit · roll untested if one side tested", exit: "50% profit OR 21 DTE mech close · stop 2× credit" },
  LONG_CALL: { entry: "45 DTE · 50Δ ATM · quality ≥40",     manage: "Trail stop at 50% max gain · re-eval at 21 DTE",        exit: "Take profit 50-100% gain · stop at 50% loss" },
  PMCC:      { entry: "LEAPS 70Δ ITM 9+mo · short 25Δ OTM", manage: "Roll short at 50% or 21 DTE · extrinsic rule",          exit: "Close if LEAPS <6mo · stop if LEAPS breached" },
};

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
  const isLongCall = cand.strategy === "LONG_CALL";
  const isMultiLeg = ["IC", "PCS", "CCS", "PMCC"].includes(cand.strategy);
  const isDirectional = isLongCall || cand.strategy === "PMCC";
  const notes = cand.notes || "";

  // Strategy badge colors
  const stratBadge: Record<string, string> = {
    PCS: "text-cyan-300", CCS: "text-rose-300",
    IC: "text-sky-300", PMCC: "text-fuchsia-300",
  };

  return (
    <button
      type="button"
      onClick={() => setExpanded((e) => !e)}
      className="w-full text-left glass rounded-xl p-3 active:bg-white/3 transition-colors space-y-2"
    >
      {/* Top row: ticker + strike + composite ring */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isLongCall || cand.strategy === "PMCC" ? (
            <Rocket size={11} className="text-violet-400 shrink-0" />
          ) : isCall ? (
            <TrendingDown size={11} className="text-amber-400 shrink-0" />
          ) : cand.strategy === "IC" ? (
            <Radar size={11} className="text-sky-400 shrink-0" />
          ) : (
            <TrendingUp size={11} className="text-emerald-400 shrink-0" />
          )}
          <span className="text-[length:var(--t-sm)] font-bold text-white">{cand.ticker}</span>
          {(isLongCall || isMultiLeg) && (
            <span className={`text-[length:var(--t-2xs)] font-semibold uppercase tracking-wide ${
              stratBadge[cand.strategy] || "text-violet-300"
            }`}>
              {cand.strategy === "LONG_CALL" ? "Long Call" : cand.strategy}
            </span>
          )}
          {!isMultiLeg && (
            <span className="text-[length:var(--t-2xs)] font-semibold text-slate-500">
              ${strike.toFixed(strike < 10 ? 1 : 0)}{cand.right}
            </span>
          )}
          <span className="text-[length:var(--t-2xs)] text-slate-600">exp {fmtExp(cand.expiry)}</span>
          {catalyst && (
            <Zap size={10} className={isDirectional ? "text-violet-400 shrink-0" : "text-orange-400 shrink-0"} />
          )}
        </div>
        <CompositeGauge value={composite} />
      </div>

      {/* Notes for multi-leg — show compact leg structure */}
      {notes && (
        <div className="text-[length:var(--t-2xs)] text-slate-500 font-mono">{notes}</div>
      )}

      {/* Key metrics */}
      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500">
        {!isMultiLeg && (
          <span>Δ <span className="text-slate-300 tabular-nums">{delta.toFixed(2)}</span></span>
        )}
        <span>{isMultiLeg ? "Credit" : "Prem"} <span className="text-slate-300 tabular-nums">{fmtPrice(prem)}</span></span>
        {isDirectional ? (
          <span>Cost <span className="text-violet-400 tabular-nums font-semibold">{fmtPrice(cash)}</span></span>
        ) : (
          <>
            <span>Yield <span className="text-emerald-400 tabular-nums font-semibold">{yld.toFixed(0)}%</span></span>
            <span>{isMultiLeg ? "Max Risk" : "Cash"} <span className="text-slate-300 tabular-nums">{fmtPrice(cash)}</span></span>
          </>
        )}
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
            <div className={`flex items-center gap-1 text-[length:var(--t-2xs)] ${isDirectional ? "text-violet-400" : "text-orange-400"}`}>
              <Zap size={10} />
              <span className="font-semibold">
                {isLongCall ? "Gov Confluence — directional catalyst" : "Catalyst — volatility elevated"}
              </span>
            </div>
          )}
          {/* 3-phase management rules */}
          {MGMT_RULES[cand.strategy] && (
            <div className="pt-1.5 border-t border-white/5 space-y-1">
              <div className="text-[length:var(--t-2xs)]">
                <span className="text-emerald-500 font-semibold">ENTRY</span>{" "}
                <span className="text-slate-500">{MGMT_RULES[cand.strategy].entry}</span>
              </div>
              <div className="text-[length:var(--t-2xs)]">
                <span className="text-amber-500 font-semibold">MANAGE</span>{" "}
                <span className="text-slate-500">{MGMT_RULES[cand.strategy].manage}</span>
              </div>
              <div className="text-[length:var(--t-2xs)]">
                <span className="text-red-400 font-semibold">EXIT</span>{" "}
                <span className="text-slate-500">{MGMT_RULES[cand.strategy].exit}</span>
              </div>
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
type StratTab = "CSP" | "CC" | "PCS" | "CCS" | "IC" | "LONG_CALL" | "PMCC";

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

  const sortByComposite = (a: ScanResultRow, b: ScanResultRow) =>
    Number(b.composite_score) - Number(a.composite_score);

  // ----- "My Tickers" lists -----
  const cspList = candidates.filter((c) => c.strategy === "CSP").sort(sortByComposite).slice(0, 8);
  const ccList = candidates.filter((c) => c.strategy === "CC").sort(sortByComposite).slice(0, 8);
  const lcList = candidates.filter((c) => c.strategy === "LONG_CALL").sort(sortByComposite).slice(0, 8);
  const pcsList = candidates.filter((c) => c.strategy === "PCS").sort(sortByComposite).slice(0, 8);
  const ccsList = candidates.filter((c) => c.strategy === "CCS").sort(sortByComposite).slice(0, 8);
  const icList = candidates.filter((c) => c.strategy === "IC").sort(sortByComposite).slice(0, 8);
  const pmccList = candidates.filter((c) => c.strategy === "PMCC").sort(sortByComposite).slice(0, 8);

  // ----- "Broad" lists -----
  const broadSort = (a: OptionRecommendationRow, b: OptionRecommendationRow) => {
    const cd = Number(b.thesis_confidence) - Number(a.thesis_confidence);
    if (!isNaN(cd) && cd !== 0) return cd;
    return Number(b.annual_yield_pct) - Number(a.annual_yield_pct);
  };
  const broadCsp = broad.filter((c) => c.strategy === "CSP").sort(broadSort).slice(0, 12);
  const broadCc = broad.filter((c) => c.strategy === "CC").sort(broadSort).slice(0, 12);
  const broadLc = broad.filter((c) => c.strategy === "LONG_CALL").sort(broadSort).slice(0, 12);

  const myLists: Record<StratTab, ScanResultRow[]> = {
    CSP: cspList, CC: ccList, PCS: pcsList, CCS: ccsList,
    IC: icList, LONG_CALL: lcList, PMCC: pmccList,
  };
  const broadLists: Record<string, OptionRecommendationRow[]> = {
    CSP: broadCsp, CC: broadCc, LONG_CALL: broadLc,
  };
  const myActive = myLists[tab] ?? [];
  const broadActive = broadLists[tab] ?? [];

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
        <div className="flex items-center gap-1 overflow-x-auto no-scrollbar">
          {([
            { key: "CSP"  as StratTab, label: "CSP",  active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" },
            { key: "CC"   as StratTab, label: "CC",   active: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
            { key: "PCS"  as StratTab, label: "PCS",  active: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30" },
            { key: "CCS"  as StratTab, label: "CCS",  active: "bg-rose-500/20 text-rose-400 border-rose-500/30" },
            { key: "IC"   as StratTab, label: "IC",   active: "bg-sky-500/20 text-sky-400 border-sky-500/30" },
            { key: "LONG_CALL" as StratTab, label: "LC", active: "bg-violet-500/20 text-violet-400 border-violet-500/30" },
            { key: "PMCC" as StratTab, label: "PMCC", active: "bg-fuchsia-500/20 text-fuchsia-400 border-fuchsia-500/30" },
          ] as const).map(({ key, label, active }) => {
            const count = onMyTickers
              ? (myLists[key]?.length ?? 0)
              : (broadLists[key]?.length ?? 0);
            return (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`px-2 py-1 rounded-md text-[length:var(--t-2xs)] font-semibold transition-all whitespace-nowrap border ${
                  tab === key ? active : "text-slate-500 hover:text-slate-300 border-transparent"
                }`}
              >
                {label}{count > 0 ? ` (${count})` : ""}
              </button>
            );
          })}
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
      ) : (onMyTickers ? myActive : broadActive).length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-4 text-slate-500">
          {tab === "LONG_CALL" || tab === "PMCC" ? (
            <>
              <Rocket size={20} className="text-slate-600" />
              <span className="text-[length:var(--t-sm)] text-center">
                No qualifying setups — waiting for trend confirmation
              </span>
              <span className="text-[length:var(--t-2xs)] text-slate-600 text-center">
                {tab === "LONG_CALL"
                  ? "Long calls require SMA50/200 uptrend + quality score ≥ 40"
                  : "PMCC requires LEAPS 9+ months + short call OTM, cost < 80% width"}
              </span>
            </>
          ) : tab === "IC" ? (
            <>
              <Radar size={20} className="text-slate-600" />
              <span className="text-[length:var(--t-sm)] text-center">
                No iron condor setups — IV may be too low
              </span>
              <span className="text-[length:var(--t-2xs)] text-slate-600 text-center">
                IVR {"≥"} 40 + credit/width {"≥"} 30% required (tastytrade rules)
              </span>
            </>
          ) : (
            <>
              <Radar size={20} className="text-slate-600" />
              <span className="text-[length:var(--t-sm)]">
                No {tab} candidates today
              </span>
            </>
          )}
        </div>
      ) : (
        <>
          <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
            {onMyTickers
              ? tab === "LONG_CALL"
                ? "Gov confluence + trend quality — score = materiality (30) + SMA trend (30) + multi-signal (25) + confirmation (15)."
                : tab === "IC"
                  ? "Iron condor — tastytrade rules: ~20Δ short strikes, $5-$10 wings, 45 DTE, IVR > 40, credit/width ≥ 30%."
                  : tab === "PCS" || tab === "CCS"
                    ? "Credit spread — tastytrade rules: 25Δ short, $5-$10 wing, 42 DTE, credit ≥ 1/3 width, IVR ≥ 25%."
                    : tab === "PMCC"
                      ? "Diagonal — LEAPS 0.70Δ ITM 9+ mo + short call 0.25Δ OTM 35 DTE, cost < 80% strike width."
                      : "My Tickers — composite = 40% technical + 25% yield + 20% IV rank + 10% cash eff + 5% liquidity."
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
