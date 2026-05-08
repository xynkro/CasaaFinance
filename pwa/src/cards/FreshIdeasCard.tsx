import type { ScreenCandidateRow, TechnicalScoreRow } from "../data";
import { Card } from "./Card";
import { Sparkles, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { StockDetail } from "../components/StockDetail";
import { numeric } from "../data";

/**
 * Fresh Ideas — surfaces the weekly vcp + canslim screener output that
 * `screen-candidates.yml` writes every Sunday. Until this card landed,
 * the screener pipeline ran but the rows never reached the user.
 *
 * Schema: `screen_candidates` sheet has `date|source|ticker|sector|score|
 * trigger_price|stop_price|rationale`. We show the latest week's rows,
 * grouped by source, sorted by score desc, capped at 8 per source.
 *
 * Tap a row → opens StockDetail with whatever technical_scores row we
 * have for that ticker (may be empty if the screen surfaced something
 * outside our daily-tech-scan universe — that's fine, StockDetail
 * gracefully degrades to TV-only).
 */
export function FreshIdeasCard({
  candidates,
  technicalScores,
  technicalScoresHistory,
}: {
  candidates: ScreenCandidateRow[];
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
}) {
  const [selected, setSelected] = useState<{ ticker: string; tech?: TechnicalScoreRow } | null>(null);

  // Latest week only, then group by source. The cron upserts per
  // (date, source, ticker) so latest run = max date prefix.
  const { vcp, canslim, latestDate } = useMemo(() => {
    if (!candidates.length) return { vcp: [], canslim: [], latestDate: "" };
    const latest = candidates.reduce(
      (acc, r) => (r.date.slice(0, 10) > acc ? r.date.slice(0, 10) : acc),
      "",
    );
    const recent = candidates.filter((r) => r.date.slice(0, 10) === latest);
    const v = recent
      .filter((r) => r.source === "vcp")
      .sort((a, b) => numeric(b.score) - numeric(a.score))
      .slice(0, 8);
    const c = recent
      .filter((r) => r.source === "canslim")
      .sort((a, b) => numeric(b.score) - numeric(a.score))
      .slice(0, 8);
    return { vcp: v, canslim: c, latestDate: latest };
  }, [candidates]);

  const techByTicker = useMemo(() => {
    const m = new Map<string, TechnicalScoreRow>();
    for (const t of technicalScores) {
      if (t.ticker) m.set(t.ticker.toUpperCase(), t);
    }
    return m;
  }, [technicalScores]);

  const handleTap = (ticker: string) => {
    const upper = ticker.toUpperCase();
    setSelected({ ticker: upper, tech: techByTicker.get(upper) });
  };

  if (!candidates.length || (!vcp.length && !canslim.length)) {
    return (
      <Card>
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="text-fuchsia-400/70" />
            <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Fresh Ideas</h2>
          </div>
          <span className="text-[length:var(--t-2xs)] text-slate-600">Weekly screen</span>
        </div>
        <p className="text-[length:var(--t-2xs)] text-slate-600 leading-relaxed">
          No candidates yet. Runs Sunday 11:00 UTC — vcp + canslim screens against the watchlist universe.
        </p>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="text-fuchsia-400/70" />
            <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Fresh Ideas</h2>
          </div>
          <span className="text-[length:var(--t-2xs)] text-slate-600">
            Week of {latestDate.slice(5)}
          </span>
        </div>

        <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
          Sunday vcp + canslim screen. Brain pulls from this when proposing
          fresh names — surfaced here so you can scan independently.
        </p>

        {vcp.length > 0 && (
          <Section
            label="VCP — volatility contraction"
            count={vcp.length}
            rows={vcp}
            onTap={handleTap}
          />
        )}
        {canslim.length > 0 && (
          <div className={vcp.length > 0 ? "mt-3" : ""}>
            <Section
              label="CANSLIM — institutional sponsorship"
              count={canslim.length}
              rows={canslim}
              onTap={handleTap}
            />
          </div>
        )}
      </Card>

      {selected && (
        <StockDetail
          ticker={selected.ticker}
          techScore={selected.tech}
          techHistory={technicalScoresHistory}
          currency="USD"
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

function Section({
  label,
  count,
  rows,
  onTap,
}: {
  label: string;
  count: number;
  rows: ScreenCandidateRow[];
  onTap: (ticker: string) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500">
          {label}
        </span>
        <span className="text-[length:var(--t-2xs)] text-slate-600">{count}</span>
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <FreshRow key={`${r.source}-${r.ticker}`} row={r} onTap={() => onTap(r.ticker)} />
        ))}
      </div>
    </div>
  );
}

function FreshRow({ row, onTap }: { row: ScreenCandidateRow; onTap: () => void }) {
  const score = numeric(row.score);
  const trigger = numeric(row.trigger_price);
  const stop = numeric(row.stop_price);
  const scoreColor = score >= 80 ? "#34d399" : score >= 60 ? "#a3e635" : "#94a3b8";

  return (
    <button
      type="button"
      onClick={onTap}
      className="w-full text-left rounded-xl px-3 py-2 active:bg-white/3 transition-colors"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker}</span>
          {row.sector && (
            <span className="text-[length:var(--t-2xs)] text-slate-500 truncate">{row.sector}</span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className="text-[length:var(--t-2xs)] font-bold tabular-nums"
            style={{ color: scoreColor }}
          >
            {score.toFixed(0)}
          </span>
          <ChevronRight size={12} className="text-slate-600" />
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-x-3 gap-y-0.5 text-[length:var(--t-2xs)] text-slate-500 mt-0.5">
        {trigger > 0 && (
          <span>
            trigger <span className="text-slate-300 tabular-nums">${trigger.toFixed(2)}</span>
          </span>
        )}
        {stop > 0 && (
          <span>
            stop <span className="text-red-300/80 tabular-nums">${stop.toFixed(2)}</span>
          </span>
        )}
      </div>

      {row.rationale && (
        <div className="text-[length:var(--t-2xs)] text-slate-500 leading-relaxed mt-1 line-clamp-2">
          {row.rationale}
        </div>
      )}
    </button>
  );
}
