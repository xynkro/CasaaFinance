/**
 * Today's ideas — the first card on Home: the daily ideas DM, in the app.
 *
 * Every string shown here is the one the Telegram DM carries, written to the
 * `daily_ideas` Sheet tab by scripts/daily_ideas_dm.py (markup stripped). This
 * card sizes, grades and formats nothing, so it cannot disagree with the DM.
 * It only lays the strings out, and decides which of four states to show:
 *   - loading with no cached data → skeleton
 *   - no rows at all             → when the list goes out, nothing sent yet
 *   - newest list is not today's → dimmed, with "Last sent <date>"
 *   - today's list               → ideas, take profits, watch, details
 */
import { useId, useState } from "react";
import type { DailyIdeaRow, TechnicalScoreRow } from "../data";
import { Card } from "./Card";
import { Chip, SectionLabel } from "../components/ui";
import { StockDetail } from "../components/StockDetail";
import { ChevronDown, ChevronRight, CircleDollarSign, Eye, Lightbulb } from "lucide-react";
import { dayLabel, etToday, sentClocks, sgtClockForEt } from "../lib/ideasTime";

// Tier colours, taken as the DM sends them (green / yellow / red).
const TIER_COLOR: Record<string, string> = {
  green: "#34d399",
  yellow: "#fbbf24",
  red: "#f87171",
};
const BUY_COLOR = "#34d399";
const SELL_COLOR = "#38bdf8";     // take-profits: distinct from buys and from the tier dots

const SEND_ET = { h: 9, mi: 45, et: "09:45" }; // "about 09:45 ET on trading days"
const FOOTER = "System research, graded against SPY. You decide; nothing here places orders.";

const T2XS = "text-[length:var(--t-2xs)]";
const TXS = "text-[length:var(--t-xs)]";
const TSM = "text-[length:var(--t-sm)]";

function Skeleton() {
  return (
    <Card variant="bright">
      <div className="flex items-center justify-between mb-3">
        <div className="shimmer h-4 w-28" />
        <div className="shimmer h-4 w-24" />
      </div>
      <div className="space-y-2">
        <div className="shimmer h-4 w-full" />
        <div className="shimmer h-4 w-5/6" />
        <div className="shimmer h-16 w-full" />
        <div className="shimmer h-16 w-full" />
      </div>
    </Card>
  );
}

function TierDot({ tier }: { tier: string }) {
  const color = TIER_COLOR[tier] ?? "#64748b";
  return (
    <span
      role="img"
      aria-label={`Source record: ${tier || "unknown"}`}
      title={`Source record: ${tier || "unknown"}`}
      className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
      style={{ background: color, boxShadow: `0 0 0 3px ${color}26` }}
    />
  );
}

/** The ticker as a tap target that opens the app's existing stock detail. */
function TickerButton({ ticker, onTap }: { ticker: string; onTap: (t: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onTap(ticker)}
      aria-label={`${ticker} details`}
      className="inline-flex items-center gap-0.5 -my-1 py-1 pr-1 rounded-lg text-[length:var(--t-lg)] font-bold text-white active:opacity-60 focusable"
    >
      {ticker}
      <ChevronRight size={14} className="text-slate-600" aria-hidden="true" />
    </button>
  );
}

function Lines({ row, showRecord = true }: { row: DailyIdeaRow; showRecord?: boolean }) {
  const notes = (row.notes ?? "").split(" | ").map((n) => n.trim()).filter(Boolean);
  return (
    <div className="mt-1.5 space-y-1 min-w-0">
      {row.plan && <p className={`${TSM} font-medium text-slate-100 leading-snug break-words`}>{row.plan}</p>}
      {row.stop && <p className={`${TXS} text-slate-300 leading-snug break-words`}>{row.stop}</p>}
      {row.size && <p className={`${TXS} text-slate-300 leading-snug break-words`}>{row.size}</p>}
      {row.why && <p className={`${TXS} text-slate-400 leading-snug break-words`}>{row.why}</p>}
      {notes.map((n, i) => (
        <p key={i} className={`${TXS} text-amber-300/90 leading-snug break-words`}>{n}</p>
      ))}
      {/* How far to trust the idea: always visible, never behind a tap. */}
      {showRecord && row.record && (
        <p className={`${TXS} text-slate-400 leading-snug break-words pt-1.5 mt-1.5 border-t border-white/5`}>
          {row.record}
        </p>
      )}
    </div>
  );
}

function IdeaRow({ row, onTap }: { row: DailyIdeaRow; onTap: (t: string) => void }) {
  return (
    <div
      className="rounded-xl px-3 py-2.5 min-w-0"
      style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
    >
      <div className="flex items-center flex-wrap gap-x-2 gap-y-1">
        <span className={`${T2XS} font-bold text-slate-500 tabular-nums`}>{row.num}</span>
        <TickerButton ticker={row.ticker} onTap={onTap} />
        <Chip color={BUY_COLOR} tone="bold">{row.action}</Chip>
        <Chip tone="medium" className="border border-slate-500/20 bg-slate-500/10 text-slate-400">{row.kind}</Chip>
        <TierDot tier={row.tier} />
        {row.status && <span className={`${T2XS} text-slate-400`}>{row.status}</span>}
      </div>
      <Lines row={row} />
    </div>
  );
}

function ExitRow({ row, onTap, showRecord }: { row: DailyIdeaRow; onTap: (t: string) => void; showRecord: boolean }) {
  return (
    <div
      className="rounded-xl pl-3 pr-3 py-2.5 min-w-0"
      style={{
        background: "rgba(56,189,248,0.05)",
        border: "1px solid rgba(56,189,248,0.14)",
        borderLeft: `3px solid ${SELL_COLOR}`,
      }}
    >
      <div className="flex items-center flex-wrap gap-x-2 gap-y-1">
        <span className={`${T2XS} font-bold text-slate-500 tabular-nums`}>{row.num}</span>
        <TickerButton ticker={row.ticker} onTap={onTap} />
        {row.account && <span className={`${TXS} font-semibold text-slate-300`}>{row.account}</span>}
        <Chip color={SELL_COLOR} tone="bold">{row.action}</Chip>
        <TierDot tier={row.tier} />
        {row.status && <span className={`${T2XS} text-slate-400`}>{row.status}</span>}
      </div>
      <Lines row={row} showRecord={showRecord} />
    </div>
  );
}

export function DailyIdeasCard({
  rows,
  loading = false,
  technicalScores,
  technicalScoresHistory,
}: {
  rows: DailyIdeaRow[];
  /** True while loading with no cached data. */
  loading?: boolean;
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
}) {
  const [selected, setSelected] = useState<{ ticker: string; tech?: TechnicalScoreRow } | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();

  if (loading) return <Skeleton />;

  const today = etToday();
  const meta = rows.find((r) => r.section === "meta");
  const ideas = rows.filter((r) => r.section === "idea");
  const exits = rows.filter((r) => r.section === "exit");
  const exitNotes = rows.filter((r) => r.section === "exit_note");   // a losing trim record: levels only
  const watch = rows.filter((r) => r.section === "watch");
  const listDate = (meta ?? rows[0])?.date?.slice(0, 10) ?? "";
  const hasList = rows.length > 0 && listDate !== "";
  const isToday = hasList && listDate === today;
  const sent = sentClocks((meta ?? rows[0])?.sent_at);

  const onTap = (ticker: string) => {
    const upper = ticker.toUpperCase();
    setSelected({ ticker: upper, tech: technicalScores.find((t) => (t.ticker ?? "").toUpperCase() === upper) });
  };

  const title = !hasList || isToday ? "Today's ideas" : "Latest ideas";
  const header = (
    <div className="flex items-start justify-between gap-3 mb-2">
      <div className="flex items-center gap-2 min-w-0">
        <Lightbulb size={16} className="text-amber-400 shrink-0" aria-hidden="true" />
        <h2 className={`${TSM} font-semibold text-slate-100`}>{title}</h2>
      </div>
      {hasList && (
        <div className="text-right shrink-0">
          {isToday ? (
            <div className={`${TXS} font-semibold text-slate-300 tabular-nums`}>{dayLabel(listDate)}</div>
          ) : (
            <div className={`${TXS} font-bold text-amber-300 tabular-nums`}>Last sent {dayLabel(listDate)}</div>
          )}
          {sent && (
            <div className={`${T2XS} text-slate-500 tabular-nums`}>
              Sent {sent.et} ET · {sent.sgt} SGT
            </div>
          )}
        </div>
      )}
    </div>
  );
  const footer = <p className={`${T2XS} text-slate-500 leading-relaxed mt-3`}>{FOOTER}</p>;

  if (!hasList) {
    return (
      <Card variant="bright">
        {header}
        <p className={`${TSM} text-slate-300 leading-relaxed`}>
          {`The list goes out about ${SEND_ET.et} ET on trading days (${sgtClockForEt(today, SEND_ET.h, SEND_ET.mi)} SGT today). Nothing has been sent yet.`}
        </p>
        {footer}
      </Card>
    );
  }

  const exitRows = [...exitNotes, ...exits];
  const sharedExitRecord =
    exitRows.length > 0 && exitRows.every((e) => e.record === exitRows[0].record) ? exitRows[0].record : "";
  const budgetLines = (meta?.budget ?? "").split(" | ").map((b) => b.trim()).filter(Boolean);
  const hasDetails = budgetLines.length > 0 || !!meta?.waiting || !!meta?.dropped;

  return (
    <>
      <Card variant="bright">
        {header}

        {/* Dimmed (not hidden) when the list is not today's, so it can't pass for today's. */}
        <div className={isToday ? "" : "opacity-60"}>
          {meta?.tape && <p className={`${TSM} text-slate-200 leading-snug break-words`}>{meta.tape}</p>}
          {meta?.lead && <p className={`${TXS} italic text-slate-400 leading-snug break-words mt-1`}>{meta.lead}</p>}

          <div className="mt-3 space-y-2">
            {ideas.map((r, i) => <IdeaRow key={`i${i}-${r.num}`} row={r} onTap={onTap} />)}
          </div>
          {ideas.length === 0 && (
            <p className={`${TSM} text-slate-300 leading-snug mt-3`}>
              No idea cleared the live check with a size today.
            </p>
          )}

          {exitRows.length > 0 && (
            <div className="mt-4">
              <SectionLabel color={SELL_COLOR} icon={<CircleDollarSign size={11} aria-hidden="true" />}>
                Take profits
              </SectionLabel>
              {sharedExitRecord && (
                <p className={`${TXS} text-slate-400 leading-snug break-words mt-1`}>{sharedExitRecord}</p>
              )}
              {exitNotes.map((r, i) => (
                <p key={`n${i}`} className={`${TXS} text-slate-300 leading-snug break-words mt-1`}>{r.plan}</p>
              ))}
              <div className="mt-2 space-y-2">
                {exits.map((r, i) => (
                  <ExitRow key={`e${i}-${r.num}`} row={r} onTap={onTap} showRecord={!sharedExitRecord} />
                ))}
              </div>
            </div>
          )}

          {watch.length > 0 && (
            <div className="mt-4">
              <SectionLabel icon={<Eye size={11} aria-hidden="true" />}>Watch — no size</SectionLabel>
              <ul className="mt-1.5 space-y-1">
                {watch.map((r, i) => (
                  <li key={`w${i}`} className={`flex gap-2 ${TXS} text-slate-400 leading-snug`}>
                    <span aria-hidden="true" className="text-slate-600">•</span>
                    <span className="min-w-0 break-words">{r.plan}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {hasDetails && (
            <div className="mt-4 border-t border-white/5 pt-2">
              <button
                type="button"
                aria-expanded={detailsOpen}
                aria-controls={detailsId}
                onClick={() => setDetailsOpen((o) => !o)}
                className="w-full flex items-center justify-between py-1.5 rounded-lg text-slate-400 active:opacity-60 focusable"
              >
                <span className={`${T2XS} uppercase font-semibold tracking-wider`}>Details</span>
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className={`transition-transform ${detailsOpen ? "rotate-180" : ""}`}
                />
              </button>
              {detailsOpen && (
                <div id={detailsId} className="mt-1.5 space-y-2.5">
                  {budgetLines.length > 0 && (
                    <div>
                      <SectionLabel>Month budget (cash + deposit)</SectionLabel>
                      <div className="mt-1 space-y-1">
                        {budgetLines.map((b, i) => (
                          <p key={i} className={`${TXS} text-slate-300 leading-snug break-words`}>{b}</p>
                        ))}
                      </div>
                    </div>
                  )}
                  {meta?.waiting && (
                    <div>
                      <SectionLabel>Waiting to trim</SectionLabel>
                      <p className={`${TXS} text-slate-300 leading-snug break-words mt-1`}>{meta.waiting}</p>
                    </div>
                  )}
                  {meta?.dropped && (
                    <div>
                      <SectionLabel>Dropped</SectionLabel>
                      <p className={`${TXS} text-slate-300 leading-snug break-words mt-1`}>{meta.dropped}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {footer}
      </Card>

      {/* The app's existing stock detail (it portals itself to <body>), as FreshIdeasCard does. */}
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
