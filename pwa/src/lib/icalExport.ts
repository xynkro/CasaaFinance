/**
 * Minimal RFC-5545 iCalendar emitter for Casaa earnings + macro events.
 *
 * No deps — we generate VCALENDAR text by hand and trigger a browser
 * download via Blob URL. Apple Calendar / Google Calendar / Outlook all
 * accept this without round-tripping through a server.
 *
 * Each event is all-day (DTSTART;VALUE=DATE) so it doesn't pollute the
 * user's hourly timeline. UID is deterministic from the source row, so
 * re-importing the same .ics deduplicates instead of creating clones.
 */
import type { EarningsRow, EconomicEventRow } from "../data";

export interface CalendarEntry {
  /** Stable UID — re-import dedupes if this matches an existing event. */
  uid: string;
  /** YYYY-MM-DD (all-day events only). */
  date: string;
  summary: string;
  description?: string;
}

/** Convert YYYY-MM-DD → YYYYMMDD. */
function toIcsDate(yyyymmdd: string): string {
  return yyyymmdd.slice(0, 10).replace(/-/g, "");
}

/** Escape commas, semicolons, newlines per RFC 5545 §3.3.11. */
function escape(s: string): string {
  return (s || "")
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

export function buildIcs(entries: CalendarEntry[]): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const lines: string[] = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Casaa Finance//Earnings & Macro Calendar//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Casaa Finance — catalysts",
    "X-WR-TIMEZONE:UTC",
  ];
  for (const e of entries) {
    lines.push(
      "BEGIN:VEVENT",
      `UID:${escape(e.uid)}`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${toIcsDate(e.date)}`,
      `SUMMARY:${escape(e.summary)}`,
    );
    if (e.description) {
      lines.push(`DESCRIPTION:${escape(e.description)}`);
    }
    lines.push("TRANSP:TRANSPARENT", "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  // RFC 5545 mandates CRLF, not just LF.
  return lines.join("\r\n");
}

export function buildEarningsEntries(rows: EarningsRow[]): CalendarEntry[] {
  return rows
    .filter((r) => r.ticker && r.date)
    .map((r) => {
      const hourTag = (r.hour || "").toUpperCase(); // BMO / AMC / DMH
      const epsEst = r.eps_estimate ? ` (est EPS $${r.eps_estimate})` : "";
      return {
        uid: `er-${r.ticker.toUpperCase()}-${r.year || "?"}-q${r.quarter || "?"}@casaa-finance`,
        date: r.date,
        summary: `📊 ${r.ticker.toUpperCase()} earnings${hourTag ? ` (${hourTag})` : ""}`,
        description: `Q${r.quarter || "?"} ${r.year || "?"}${epsEst}`,
      };
    });
}

export function buildMacroEntries(rows: EconomicEventRow[]): CalendarEntry[] {
  return rows
    .filter((r) => r.event && r.date)
    .map((r) => {
      const country = r.country ? `[${r.country}] ` : "";
      const time = r.time ? ` @ ${r.time}` : "";
      const forecast = r.forecast ? ` · est ${r.forecast}${r.unit || ""}` : "";
      const previous = r.previous ? ` · prev ${r.previous}${r.unit || ""}` : "";
      return {
        uid: `macro-${r.date}-${(r.event || "").replace(/\s+/g, "-").toLowerCase()}-${r.country || "x"}@casaa-finance`,
        date: r.date,
        summary: `🌐 ${country}${r.event}${time}`,
        description: `${(r.impact || "").toUpperCase()} impact${forecast}${previous}`,
      };
    });
}

/**
 * Trigger a browser download of an .ics file. Works on iOS Safari, Mac
 * Safari, Chrome, Firefox. The user's calendar app prompts to import
 * once they tap the file in Files / Downloads.
 */
export function downloadIcs(filename: string, ics: string): void {
  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Free the blob — small, but tidy.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
