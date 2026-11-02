/**
 * ideasTime — the clock maths for the Home "Today's ideas" card.
 *
 * The ideas DM stamps `sent_at` as NAIVE US-Eastern wall clock
 * ("2026-11-02T09:45"). Caspar reads it in Singapore, so the card shows both.
 * The ET→SGT gap is 13h in US winter and 12h in US summer, so it is worked out
 * with Intl (which carries the DST rules) rather than a fixed offset.
 */

const ET = "America/New_York";
const SGT = "Asia/Singapore";

const dtfCache = new Map<string, Intl.DateTimeFormat>();
function dtf(key: string, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  let f = dtfCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", opts);
    dtfCache.set(key, f);
  }
  return f;
}

function partsOf(f: Intl.DateTimeFormat, ms: number): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of f.formatToParts(new Date(ms))) out[p.type] = p.value;
  return out;
}

/** The wall clock an instant shows in `tz`, expressed as a UTC timestamp. */
function wallClockMs(ms: number, tz: string): number {
  const p = partsOf(
    dtf(`wall|${tz}`, {
      timeZone: tz, hourCycle: "h23",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }),
    ms,
  );
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
}

export interface NaiveStamp { date: string; h: number; mi: number }

/** "2026-11-02T09:45" (also "2026-11-02 09:45:00") → parts, or null. */
export function parseNaiveStamp(s: string | undefined | null): NaiveStamp | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})/.exec((s ?? "").trim());
  if (!m) return null;
  const h = +m[4], mi = +m[5];
  if (h > 23 || mi > 59) return null;
  return { date: `${m[1]}-${m[2]}-${m[3]}`, h, mi };
}

/** The instant (ms since epoch) at which New York's wall clock read date + h:mi. */
export function etWallToInstant(date: string, h: number, mi: number): number {
  const [y, mo, d] = date.split("-").map(Number);
  const naive = Date.UTC(y, mo - 1, d, h, mi);
  // First guess uses the offset in force at `naive`; the second corrects it when
  // the stamp sits on the other side of a DST change from that guess.
  const first = naive - (wallClockMs(naive, ET) - naive);
  return naive - (wallClockMs(first, ET) - first);
}

function hhmm(h: number, mi: number): string {
  return `${String(h).padStart(2, "0")}:${String(mi).padStart(2, "0")}`;
}

/** Singapore clock "HH:MM" for the instant New York's wall clock read date + h:mi. */
export function sgtClockForEt(date: string, h: number, mi: number): string {
  const p = partsOf(
    dtf("sgt", { timeZone: SGT, hourCycle: "h23", hour: "2-digit", minute: "2-digit" }),
    etWallToInstant(date, h, mi),
  );
  return hhmm(+p.hour, +p.minute);
}

/** "Sent 09:45 ET · 22:45 SGT" pieces for a `sent_at` stamp, or null if unreadable. */
export function sentClocks(sentAt: string | undefined | null): { et: string; sgt: string } | null {
  const s = parseNaiveStamp(sentAt);
  if (!s) return null;
  return { et: hhmm(s.h, s.mi), sgt: sgtClockForEt(s.date, s.h, s.mi) };
}

/** Today's date in New York, "YYYY-MM-DD". */
export function etToday(now: Date = new Date()): string {
  const p = partsOf(dtf("etdate", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" }), now.getTime());
  return `${p.year}-${p.month}-${p.day}`;
}

/** "Mon 2 Nov" for a "YYYY-MM-DD" calendar date (no timezone shifting). */
export function dayLabel(date: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? "");
  if (!m) return date ?? "";
  const p = partsOf(
    dtf("daylabel", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" }),
    Date.UTC(+m[1], +m[2] - 1, +m[3]),
  );
  return `${p.weekday} ${p.day} ${p.month}`;
}
