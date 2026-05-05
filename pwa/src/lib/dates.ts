/**
 * Canonical date helpers — formerly duplicated 6× across modals/pages/cards.
 *
 * Two formats supported (matching what the prior copy-paste copies emitted):
 *   - shortDate("2026-04-30")       → "Apr 30"          (HistoryPage / ClosedDecisionsCard)
 *   - shortDateLong("2026-04-30")   → "30 Apr 2026"     (Archive/Brief/Wsr/Lite modals)
 *
 * Both accept any ISO-ish string and slice the first 10 chars (YYYY-MM-DD)
 * before parsing — so "2026-04-30T15:23:00Z" works the same as "2026-04-30".
 */
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Apr 30" — used by chart axes and compact list rows. */
export function shortDate(d: string): string {
  const s = d.slice(0, 10);
  const [, m, day] = s.split("-");
  if (!m || !day) return s;
  return `${MONTHS[Number(m)]} ${Number(day)}`;
}

/** "30 Apr 2026" — used by modal headers / archive rows where the year matters. */
export function shortDateLong(d: string): string {
  const s = d.slice(0, 10);
  const [y, m, day] = s.split("-");
  if (!y || !m || !day) return s;
  return `${Number(day)} ${MONTHS[Number(m)]} ${y}`;
}

/**
 * Whole-day difference between today (local) and the given ISO-ish date.
 *
 * Accepts any string whose first 10 characters parse as YYYY-MM-DD — the
 * brain emits timestamps like "2026-05-04T202524" (no colons), so we slice
 * before parsing rather than handing the raw string to `new Date`.
 *
 * Returns a non-negative integer:
 *   - 0  → today (or future date — we don't bother distinguishing)
 *   - 1  → yesterday
 *   - 7  → one week ago
 *
 * Used by the Decisions tab age chip to flag stale brain prose.
 */
export function daysAgo(iso: string): number {
  const s = (iso ?? "").slice(0, 10);
  const [y, m, day] = s.split("-");
  if (!y || !m || !day) return 0;
  const then = new Date(Number(y), Number(m) - 1, Number(day));
  const now = new Date();
  // Zero out the time-of-day on `now` so partial days don't tip the count.
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffMs = today.getTime() - then.getTime();
  if (diffMs <= 0) return 0;
  return Math.floor(diffMs / 86_400_000);
}
