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
