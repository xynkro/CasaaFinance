/**
 * decisions/MfWatchlistStrip.tsx — read-only Motley Fool watchlist strip.
 *
 * Split verbatim out of the original monolithic ``DecisionsPage.tsx`` — behavior
 * and visual output are unchanged. This is RESEARCH, not a buy: nothing here is
 * auto-traded.
 */
import type { CuratedPickRow } from "../../data";
import { Card } from "../../cards/Card";
import { BookOpen } from "lucide-react";

/**
 * Motley Fool watchlist strip — read-only chips of tickers MF flagged as new
 * recs / rankings. This is RESEARCH, not a buy: nothing here is auto-traded.
 * Renders null when empty (no first-deploy stub).
 */
export function MfWatchlistStrip({ watchlist }: { watchlist: CuratedPickRow[] }) {
  if (!watchlist.length) return null;
  // de-dup by ticker (a name can appear once per role-row)
  const seen = new Set<string>();
  const picks = watchlist.filter((r) => {
    const t = (r.ticker || "").toUpperCase();
    if (!t || seen.has(t)) return false;
    seen.add(t);
    return true;
  });
  return (
    <Card>
      <div className="flex items-center gap-2 mb-1.5">
        <BookOpen size={14} className="text-fuchsia-400" />
        <h3 className="text-[length:var(--t-sm)] font-medium text-slate-400">Motley Fool Watchlist</h3>
        <span className="text-[length:var(--t-2xs)] text-slate-600">research, not a buy</span>
      </div>
      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-2 leading-relaxed">
        New recs &amp; rankings from MF Stock Advisor — reference input, not auto-traded.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {picks.map((r, i) => (
          <span
            key={`${r.ticker}-${i}`}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-fuchsia-500/10 border border-fuchsia-500/20 text-[length:var(--t-xs)]"
            title={r.note || "Motley Fool watchlist"}
          >
            <span className="font-bold text-white">{r.ticker}</span>
            {r.mf_type && <span className="text-[length:var(--t-2xs)] text-fuchsia-300">{r.mf_type}</span>}
          </span>
        ))}
      </div>
    </Card>
  );
}
