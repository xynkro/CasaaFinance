import type { TechnicalScoreRow } from "../data";
import { Card } from "./Card";
import { TrendingUp, ChevronRight, Zap } from "lucide-react";
import { useState } from "react";
import { StockDetail } from "../components/StockDetail";

const MIN_BUY_SCORE = 15;  // threshold to appear

function fmtPrice(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toFixed(2)}`;
}

function BuyScoreRing({ value }: { value: number }) {
  const radius = 13;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(100, value));
  const offset = circumference * (1 - progress / 100);
  const color = value >= 50 ? "#10b981" : value >= 30 ? "#34d399" : "#64748b";

  return (
    <div className="relative flex items-center justify-center" style={{ width: 34, height: 34 }}>
      <svg width="34" height="34" className="rotate-[-90deg]">
        <circle cx="17" cy="17" r={radius} stroke="rgba(255,255,255,0.08)" strokeWidth="2.5" fill="none" />
        <circle
          cx="17" cy="17" r={radius}
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

function BuyItem({ row, onTap }: { row: TechnicalScoreRow; onTap: () => void }) {
  const buyScore = Number(row.score_buy);
  const close = Number(row.close);
  const support = Number(row.support);
  const resistance = Number(row.resistance);
  const rsi = Number(row.rsi_14);
  const catalyst = row.catalyst_flag === "TRUE";
  const signal = row.entry_exit_signal;
  const trend = row.trend;

  // Distance to support/resistance as % of price
  const toSupport = support > 0 && close > 0 ? ((close - support) / close) * 100 : null;
  const toResistance = resistance > 0 && close > 0 ? ((resistance - close) / close) * 100 : null;

  return (
    <button
      type="button"
      onClick={onTap}
      className="w-full text-left glass rounded-xl p-3 active:bg-white/3 transition-colors space-y-2"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <BuyScoreRing value={buyScore} />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-bold text-white">{row.ticker}</span>
              {catalyst && <Zap size={10} className="text-orange-400 shrink-0" />}
            </div>
            <div className="text-[10px] text-slate-500">{trend} · {fmtPrice(close)}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[10px] font-bold ${
            signal === "BUY" ? "text-emerald-400" :
            signal?.startsWith("SELL") ? "text-red-400" : "text-slate-400"
          }`}>
            {signal || "HOLD"}
          </span>
          <ChevronRight size={12} className="text-slate-600" />
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
        <span>RSI <span className={`tabular-nums ${
          rsi > 70 ? "text-red-400" : rsi < 30 ? "text-amber-400" : "text-slate-300"
        }`}>{rsi.toFixed(0)}</span></span>
        {toSupport !== null && (
          <span>to Sup <span className="text-emerald-400 tabular-nums">{toSupport.toFixed(1)}%</span></span>
        )}
        {toResistance !== null && (
          <span>to Res <span className="text-red-400 tabular-nums">{toResistance.toFixed(1)}%</span></span>
        )}
      </div>

      {row.top_drivers && (
        <div className="text-[10px] text-slate-500 leading-relaxed">
          {row.top_drivers.split("|").find((s) => s.trim().startsWith("BUY")) ?? row.top_drivers.split("|")[0]}
        </div>
      )}
    </button>
  );
}

export function BuyRecommendationsCard({
  technicalScores,
  technicalScoresHistory,
}: {
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
}) {
  const [selected, setSelected] = useState<TechnicalScoreRow | null>(null);

  // Filter + sort
  const candidates = technicalScores
    .filter((t) => Number(t.score_buy) >= MIN_BUY_SCORE)
    .sort((a, b) => Number(b.score_buy) - Number(a.score_buy))
    .slice(0, 8);

  if (!candidates.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <TrendingUp size={16} />
          <span className="text-sm">Buy ideas — no candidates scoring above {MIN_BUY_SCORE}</span>
        </div>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <TrendingUp size={14} className="text-emerald-400" />
            <h2 className="text-sm font-medium text-slate-400">Stock Buy Ideas</h2>
          </div>
          <span className="text-[10px] text-slate-600">{candidates.length} ranked by BUY score</span>
        </div>

        <p className="text-[10px] text-slate-600 mb-3 leading-relaxed">
          From the daily technical scan: tickers where the environment favors stock buys.
          Tap for full analysis.
        </p>

        <div className="space-y-2">
          {candidates.map((t) => (
            <BuyItem key={t.ticker} row={t} onTap={() => setSelected(t)} />
          ))}
        </div>
      </Card>

      {selected && (
        <StockDetail
          ticker={selected.ticker}
          techScore={selected}
          techHistory={technicalScoresHistory}
          currency="USD"
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
