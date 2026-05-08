import type { EarningsRow, EconomicEventRow } from "../data";
import { Card } from "./Card";
import { Calendar, Globe2, Download } from "lucide-react";
import {
  buildEarningsEntries,
  buildIcs,
  buildMacroEntries,
  downloadIcs,
} from "../lib/icalExport";

/**
 * Upcoming Calendars card — shows the next 7 days of earnings (filtered
 * to portfolio + watchlist tickers) + high-impact macro events. Lives
 * on Home as a single side-by-side widget so the user sees the week's
 * catalysts at a glance.
 *
 * Data sources:
 *   - earnings_calendar (Finnhub) — populated daily by finnhub-calendars.yml
 *   - economic_calendar (Finnhub) — same cron
 *
 * Both are null-safe; renders skeleton-style placeholder when both
 * arrays are empty (catches first-deploy state before the cron has
 * landed).
 */
export function UpcomingCalendarsCard({
  earnings,
  events,
}: {
  earnings: EarningsRow[];
  events: EconomicEventRow[];
}) {
  const today = new Date().toISOString().slice(0, 10);
  const end7d = (() => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() + 7);
    return d.toISOString().slice(0, 10);
  })();

  // Filter both to today → +7 days, sort by date.
  const erUpcoming = earnings
    .filter((e) => e.date && e.date >= today && e.date <= end7d)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 8);

  const macroUpcoming = events
    .filter((m) =>
      m.date && m.date >= today && m.date <= end7d &&
      // Only HIGH impact for the Home widget — medium clutter the screen
      (m.impact || "").toLowerCase() === "high",
    )
    .sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`))
    .slice(0, 8);

  if (erUpcoming.length === 0 && macroUpcoming.length === 0) return null;

  // Export the visible 7-day window only — keeps the .ics small enough
  // that re-imports don't accumulate noise. The user can re-tap weekly
  // to refresh; UIDs are deterministic so duplicates dedupe in their
  // calendar app.
  const handleExport = () => {
    const entries = [
      ...buildEarningsEntries(erUpcoming),
      ...buildMacroEntries(macroUpcoming),
    ];
    if (!entries.length) return;
    const today = new Date().toISOString().slice(0, 10);
    downloadIcs(`casaa-catalysts-${today}.ics`, buildIcs(entries));
  };

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Calendar size={14} className="text-amber-400" />
          <span className="text-[length:var(--t-sm)] font-semibold text-slate-300">
            Week ahead
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--t-2xs)] text-slate-600">next 7 days</span>
          <button
            type="button"
            onClick={handleExport}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-[length:var(--t-2xs)] font-medium text-slate-400 hover:text-amber-300 active:scale-95 transition"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
            title="Export to your calendar (.ics)"
            aria-label="Export catalysts to calendar"
          >
            <Download size={10} />
            <span>iCal</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* Earnings column */}
        <div>
          <div className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500 mb-2">
            Earnings
          </div>
          {erUpcoming.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {erUpcoming.map((e) => (
                <li
                  key={`${e.ticker}-${e.year}-${e.quarter}`}
                  className="flex items-center justify-between text-[length:var(--t-xs)]"
                  title={`${e.ticker} Q${e.quarter} ${e.year}${e.eps_estimate ? ` · est $${e.eps_estimate}` : ""}`}
                >
                  <span className="font-semibold text-slate-200 tabular-nums">
                    {e.date.slice(5)}
                  </span>
                  <span className="text-slate-100 font-mono">{e.ticker}</span>
                  <span className="text-[length:var(--t-2xs)] text-slate-500">
                    {(e.hour || "").toUpperCase()}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[length:var(--t-xs)] text-slate-600">None</p>
          )}
        </div>

        {/* Macro column */}
        <div>
          <div className="flex items-center gap-1 mb-2">
            <Globe2 size={10} className="text-slate-500" />
            <span className="text-[length:var(--t-2xs)] uppercase font-semibold tracking-wider text-slate-500">
              Macro (high)
            </span>
          </div>
          {macroUpcoming.length > 0 ? (
            <ul className="flex flex-col gap-1.5">
              {macroUpcoming.map((m, i) => (
                <li
                  key={`${m.date}-${m.event}-${i}`}
                  className="flex items-baseline justify-between gap-1.5 text-[length:var(--t-xs)]"
                  title={`${m.date} ${m.time} ${m.country} · ${m.event}${m.forecast ? ` · est ${m.forecast}` : ""}`}
                >
                  <span className="font-semibold text-slate-200 tabular-nums shrink-0">
                    {m.date.slice(5)}
                  </span>
                  <span className="text-slate-300 truncate">{m.event}</span>
                  <span className="text-[length:var(--t-2xs)] text-slate-500 shrink-0">
                    {m.country}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[length:var(--t-xs)] text-slate-600">None</p>
          )}
        </div>
      </div>
    </Card>
  );
}
