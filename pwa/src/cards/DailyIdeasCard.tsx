/**
 * Today's ideas — the first card on Home: the daily ideas DM, in the app.
 *
 * Every string shown here is the one the Telegram DM carries, written to the
 * `daily_ideas` Sheet tab by scripts/daily_ideas_dm.py (markup stripped). This
 * card sizes, grades and formats nothing, so it cannot disagree with the DM.
 * It only lays the strings out, and decides which of four states to show:
 *   - loading with no cached data → skeleton
 *   - no rows at all             → when the plan and the re-check go out, nothing sent yet
 *   - newest list is not today's → dimmed, with "Last sent <date>"
 *   - today's list               → direction, then each book, then details
 *
 * A list with `book` rows is laid out per book, stacked (never tabbed, so one
 * book's actions are never behind a tap). A list without them is the older flat
 * layout, kept as it was so lists sent before the split still read the same.
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
const PUT_COLOR = "#a78bfa";   // selling a put: neither the buy nor the sell colour

const PLAN_ET = { h: 8, mi: 45, et: "08:45" };     // pre-open plan: "about 08:45 ET on trading days"
const RECHECK_ET = { h: 9, mi: 47, et: "09:47" };  // re-check on live prices
const FOOTER = "System research, graded against SPY. You decide; nothing here places orders.";

const T2XS = "text-[length:var(--t-2xs)]";
const TXS = "text-[length:var(--t-xs)]";
const TSM = "text-[length:var(--t-sm)]";

/** A " | "-joined column as lines. Tolerates the column being absent (old caches). */
function splitLines(s: string | undefined): string[] {
  return (s ?? "").split(" | ").map((n) => n.trim()).filter(Boolean);
}

/** Account names compared loosely, so "Sarah " and "sarah" are the same book. */
function acct(s: string | undefined): string {
  return (s ?? "").trim().toLowerCase();
}

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
  const notes = splitLines(row.notes);
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

/** `showAccount` is off inside a book section, which already says whose it is. */
function ExitRow({
  row, onTap, showRecord, showAccount = true,
}: { row: DailyIdeaRow; onTap: (t: string) => void; showRecord: boolean; showAccount?: boolean }) {
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
        {showAccount && row.account && <span className={`${TXS} font-semibold text-slate-300`}>{row.account}</span>}
        <Chip color={SELL_COLOR} tone="bold">{row.action}</Chip>
        <TierDot tier={row.tier} />
        {row.status && <span className={`${T2XS} text-slate-400`}>{row.status}</span>}
      </div>
      <Lines row={row} showRecord={showRecord} />
    </div>
  );
}

/** Cash-secured puts this book's cash covers, then the lines that say what doesn't fit. */
function PutLines({
  puts, putNotes, onTap, className = "mt-3",
}: { puts: DailyIdeaRow[]; putNotes: DailyIdeaRow[]; onTap: (t: string) => void; className?: string }) {
  if (puts.length + putNotes.length === 0) return null;
  return (
    <div className={className}>
      <SectionLabel color={PUT_COLOR} icon={<CircleDollarSign size={11} aria-hidden="true" />}>
        Puts this cash covers
      </SectionLabel>
      <div className="mt-2 space-y-2">
        {puts.map((r, i) => (
          <div
            key={`p${i}-${r.num}`}
            className="rounded-xl pl-3 pr-3 py-2.5 min-w-0"
            style={{
              background: "rgba(167,139,250,0.05)",
              border: "1px solid rgba(167,139,250,0.14)",
              borderLeft: `3px solid ${PUT_COLOR}`,
            }}
          >
            <div className="flex items-center flex-wrap gap-x-2 gap-y-1">
              <span className={`${T2XS} font-bold text-slate-500 tabular-nums`}>{r.num}</span>
              <TickerButton ticker={r.ticker} onTap={onTap} />
              <Chip color={PUT_COLOR} tone="bold">{r.action}</Chip>
            </div>
            <Lines row={r} showRecord={false} />
          </div>
        ))}
      </div>
      {putNotes.map((n, i) => (
        <p key={`pn${i}`} className={`${TXS} text-slate-400 leading-snug break-words mt-2`}>{n.plan}</p>
      ))}
    </div>
  );
}

/** Take-profit rows for one list or one book. Renders nothing when there are none. */
function TakeProfits({
  exitNotes, exits, onTap, showAccount, className = "mt-4",
}: {
  exitNotes: DailyIdeaRow[];
  exits: DailyIdeaRow[];
  onTap: (t: string) => void;
  showAccount: boolean;
  className?: string;
}) {
  const exitRows = [...exitNotes, ...exits];
  if (exitRows.length === 0) return null;
  const sharedExitRecord = exitRows.every((e) => e.record === exitRows[0].record) ? exitRows[0].record : "";
  return (
    <div className={className}>
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
          <ExitRow key={`e${i}-${r.num}`} row={r} onTap={onTap} showRecord={!sharedExitRecord} showAccount={showAccount} />
        ))}
      </div>
    </div>
  );
}

function WatchList({ rows, className = "mt-4" }: { rows: DailyIdeaRow[]; className?: string }) {
  if (rows.length === 0) return null;
  return (
    <div className={className}>
      <SectionLabel icon={<Eye size={11} aria-hidden="true" />}>Watch — no size</SectionLabel>
      <ul className="mt-1.5 space-y-1">
        {rows.map((r, i) => (
          <li key={`w${i}`} className={`flex gap-2 ${TXS} text-slate-400 leading-snug`}>
            <span aria-hidden="true" className="text-slate-600">•</span>
            <span className="min-w-0 break-words">{r.plan}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Prices, then the plan's direction and levels, then the re-check time, then the
 * sizing note. Direction, levels and re-check are absent on the open list and on
 * older lists, which leaves just the tape and the sizing note, as it always was.
 */
function Direction({ meta }: { meta: DailyIdeaRow | undefined }) {
  const direction = splitLines(meta?.direction);
  const levels = splitLines(meta?.levels);
  const hasPlan = direction.length > 0 || levels.length > 0 || !!meta?.recheck;
  return (
    <>
      {meta?.tape && <p className={`${TSM} text-slate-200 leading-snug break-words`}>{meta.tape}</p>}
      {hasPlan && (
        <div className="mt-2 pl-3 space-y-1 min-w-0" style={{ borderLeft: "2px solid rgba(255,255,255,0.18)" }}>
          {direction.map((d, i) => (
            <p key={`d${i}`} className={`${TSM} font-medium text-slate-100 leading-snug break-words`}>{d}</p>
          ))}
          {levels.map((l, i) => (
            <p key={`l${i}`} className={`${TXS} text-slate-300 leading-snug break-words`}>{l}</p>
          ))}
          {meta?.recheck && <p className={`${T2XS} text-slate-500 leading-snug break-words`}>{meta.recheck}</p>}
        </div>
      )}
      {meta?.lead && (
        <p className={`${TXS} italic text-slate-400 leading-snug break-words ${hasPlan ? "mt-2" : "mt-1"}`}>{meta.lead}</p>
      )}
    </>
  );
}

/**
 * One book (an account): header with the cash headline and the status summary,
 * the data warning right under it, then this book's buys, take profits and
 * supporting lines. `book` is absent for the catch-all section of rows that name
 * no book on the list, so none of them is dropped.
 */
function BookSection({
  name, book, ideas, exitNotes, exits, puts = [], putNotes = [], watch, onTap,
}: {
  name: string;
  book?: DailyIdeaRow;
  ideas: DailyIdeaRow[];
  exitNotes: DailyIdeaRow[];
  exits: DailyIdeaRow[];
  puts?: DailyIdeaRow[];
  putNotes?: DailyIdeaRow[];
  watch: DailyIdeaRow[];
  onTap: (t: string) => void;
}) {
  const budgetLines = splitLines(book?.budget);
  const earnings = splitLines(book?.notes);
  const hasActions = ideas.length + exits.length + puts.length > 0;
  return (
    <section aria-label={name} className="mt-4 pt-3 border-t border-white/10 min-w-0">
      <div className="flex items-center justify-between gap-3">
        <h3 className={`${TSM} font-bold text-slate-100 min-w-0 break-words`}>{name}</h3>
        {book?.status && (
          hasActions
            ? <Chip color="#e2e8f0" tone="bold" className="shrink-0">{book.status}</Chip>
            : <Chip tone="medium" className="shrink-0 border border-slate-500/20 bg-slate-500/10 text-slate-400">{book.status}</Chip>
        )}
      </div>
      {book?.plan && <p className={`${TXS} text-slate-300 leading-snug break-words mt-0.5`}>{book.plan}</p>}
      {/* A data warning can change what to do, so it is amber, boxed and never folded. */}
      {book?.warning && (
        <p
          role="note"
          className={`${TXS} font-semibold text-amber-200 leading-snug break-words mt-2 rounded-lg px-2.5 py-2`}
          style={{ background: "rgba(251,191,36,0.12)", border: "1px solid rgba(251,191,36,0.45)" }}
        >
          {book.warning}
        </p>
      )}

      {ideas.length > 0 && (
        <div className="mt-3 space-y-2">
          {ideas.map((r, i) => <IdeaRow key={`i${i}-${r.num}`} row={r} onTap={onTap} />)}
        </div>
      )}
      <TakeProfits exitNotes={exitNotes} exits={exits} onTap={onTap} showAccount={false} className="mt-3" />
      <PutLines puts={puts} putNotes={putNotes} onTap={onTap} />

      {(budgetLines.length > 0 || earnings.length > 0 || !!book?.waiting) && (
        <div className="mt-3 space-y-1">
          {budgetLines.map((b, i) => (
            <p key={`b${i}`} className={`${TXS} text-slate-400 leading-snug break-words`}>{b}</p>
          ))}
          {earnings.map((n, i) => (
            <p key={`n${i}`} className={`${TXS} text-amber-300/90 leading-snug break-words`}>{n}</p>
          ))}
          {book?.waiting && (
            <p className={`${TXS} text-slate-400 leading-snug break-words`}>
              <span className="text-slate-500">Waiting for a level: </span>{book.waiting}
            </p>
          )}
        </div>
      )}

      <WatchList rows={watch} className="mt-3" />
      {book?.dropped && (
        <p className={`${TXS} text-slate-500 leading-snug break-words mt-2`}>Dropped: {book.dropped}</p>
      )}
    </section>
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
  const puts = rows.filter((r) => r.section === "put");
  const putNotes = rows.filter((r) => r.section === "put_note");
  const watch = rows.filter((r) => r.section === "watch");
  const listDate = (meta ?? rows[0])?.date?.slice(0, 10) ?? "";
  const hasList = rows.length > 0 && listDate !== "";
  const isToday = hasList && listDate === today;
  const sent = sentClocks((meta ?? rows[0])?.sent_at);

  const onTap = (ticker: string) => {
    const upper = ticker.toUpperCase();
    setSelected({ ticker: upper, tech: technicalScores.find((t) => (t.ticker ?? "").toUpperCase() === upper) });
  };

  // The pre-open plan keeps its own title; "Last sent" below still marks it stale.
  const preopen = (meta?.phase ?? "").trim().toLowerCase() === "preopen";
  const title = preopen ? "Pre-open plan" : !hasList || isToday ? "Today's ideas" : "Latest ideas";
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
          {`The plan goes out about ${PLAN_ET.et} ET on trading days (${sgtClockForEt(today, PLAN_ET.h, PLAN_ET.mi)} SGT today), and the re-check about ${RECHECK_ET.et} ET (${sgtClockForEt(today, RECHECK_ET.h, RECHECK_ET.mi)} SGT). Nothing has been sent yet.`}
        </p>
        {footer}
      </Card>
    );
  }

  const budgetLines = splitLines(meta?.budget);
  const hasDetails = budgetLines.length > 0 || !!meta?.waiting || !!meta?.dropped;

  // Per-book layout. A row that names a book goes under that book; a row whose
  // account matches no book (or an idea/exit with none) goes in "Other" rather than
  // vanishing, and a watch line with no account is for both books.
  const books = rows.filter((r) => r.section === "book");
  const hasBooks = books.length > 0;
  const bookKeys = new Set(books.map((b) => acct(b.account)));
  const forBook = (rs: DailyIdeaRow[], b: DailyIdeaRow) => rs.filter((r) => acct(r.account) === acct(b.account));
  const noBook = (r: DailyIdeaRow) => !bookKeys.has(acct(r.account));
  const bothWatch = watch.filter((r) => acct(r.account) === "");
  const other = {
    ideas: ideas.filter(noBook),
    exitNotes: exitNotes.filter(noBook),
    exits: exits.filter(noBook),
    watch: watch.filter((r) => acct(r.account) !== "" && noBook(r)),
  };
  const hasOther = other.ideas.length + other.exitNotes.length + other.exits.length + other.watch.length > 0;

  const details = hasDetails && (
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
  );

  return (
    <>
      <Card variant="bright">
        {header}

        {/* Dimmed (not hidden) when the list is not today's, so it can't pass for today's. */}
        <div className={isToday ? "" : "opacity-60"}>
          <Direction meta={meta} />

          {hasBooks ? (
            <>
              {/* Stacked, in the order the list sends them: no tabs, so nothing is behind a tap. */}
              {books.map((b, i) => (
                <BookSection
                  key={`b${i}-${b.account}`}
                  name={b.account || "Book"}
                  book={b}
                  ideas={forBook(ideas, b)}
                  exitNotes={forBook(exitNotes, b)}
                  exits={forBook(exits, b)}
                  puts={forBook(puts, b)}
                  putNotes={forBook(putNotes, b)}
                  watch={forBook(watch, b)}
                  onTap={onTap}
                />
              ))}
              {hasOther && <BookSection name="Other" {...other} onTap={onTap} />}
              {bothWatch.length > 0 && (
                <section aria-label="Both books" className="mt-4 pt-3 border-t border-white/10 min-w-0">
                  <h3 className={`${TSM} font-bold text-slate-100`}>Both books</h3>
                  <WatchList rows={bothWatch} className="mt-2" />
                </section>
              )}
            </>
          ) : (
            <>
              <div className="mt-3 space-y-2">
                {ideas.map((r, i) => <IdeaRow key={`i${i}-${r.num}`} row={r} onTap={onTap} />)}
              </div>
              {ideas.length === 0 && (
                <p className={`${TSM} text-slate-300 leading-snug mt-3`}>
                  No idea cleared the live check with a size today.
                </p>
              )}
              <TakeProfits exitNotes={exitNotes} exits={exits} onTap={onTap} showAccount />
              <WatchList rows={watch} />
            </>
          )}

          {details}
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
