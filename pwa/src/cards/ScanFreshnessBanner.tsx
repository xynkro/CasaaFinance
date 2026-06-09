import type { ScanMetaRow, ScanResultRow } from "../data";
import { Card } from "./Card";
import { RefreshCw, AlertTriangle } from "lucide-react";

/** run_at is written naive-UTC by the CI scanner ("…T02:56:51"); treat a
 *  suffix-less stamp as UTC so the relative time is correct on the user's
 *  device. */
function relTime(iso: string): string {
  if (!iso) return "";
  const ms = Date.parse(/[Z+]/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(ms)) return iso.slice(0, 16).replace("T", " ");
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

const dayOf = (s: string): string => (s || "").slice(0, 10);

/**
 * Last-scan freshness marker for the Options page. The scanner writes a
 * `scan_meta` heartbeat every run (even zero-candidate runs); pairing its
 * `run_at` with the date stamped on the scan_results rows tells us whether the
 * candidates on screen are current or frozen. Quiet line when fresh; an amber
 * warning when a more recent scan produced nothing and left stale data behind
 * — the exact case that used to silently show days-old picks.
 */
export function ScanFreshnessBanner({
  scanMeta,
  scanResults,
}: {
  scanMeta: ScanMetaRow | null;
  scanResults: ScanResultRow[];
}) {
  if (!scanMeta?.run_at) return null;

  const runDay = dayOf(scanMeta.run_at);
  let dataDay = "";
  for (const r of scanResults) {
    const d = dayOf(r.date);
    if (d > dataDay) dataDay = d;
  }
  const lastRunCount = Number(scanMeta.candidates) || 0;  // last run's count (may be a 0-run)
  const shownCount = scanResults.length;                  // picks actually on screen
  const when = relTime(scanMeta.run_at);
  // Stale ⇒ a scan ran AFTER the data on screen was last written: that run
  // produced nothing and left the prior candidates frozen. Same-day refreshes
  // and a same-day 0-run never trip this (the data is still today's).
  const frozen = !!dataDay && !!runDay && dataDay < runDay;

  if (frozen) {
    return (
      <Card>
        <div className="flex items-start gap-2">
          <AlertTriangle size={15} className="text-amber-400 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="text-[length:var(--t-xs)] font-semibold text-amber-300">
              Showing {shownCount} pick{shownCount === 1 ? "" : "s"} from {dataDay} — likely stale
            </p>
            <p className="text-[length:var(--t-2xs)] text-slate-400 mt-0.5 leading-relaxed">
              Last scan ran {when} and found {lastRunCount}
              {scanMeta.status === "HALTED" ? " (macro HALT)" : " (likely a yfinance hiccup)"} — so
              the candidates below are from the last good run. Re-run the Options scan to refresh.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center gap-2 flex-wrap">
        <RefreshCw size={13} className="text-emerald-400/80 shrink-0" />
        <span className="text-[length:var(--t-2xs)] text-slate-400">
          Scan {when} ·{" "}
          {shownCount > 0 ? (
            <>
              <span className="text-slate-300 font-semibold tabular-nums">{shownCount}</span>{" "}
              candidate{shownCount === 1 ? "" : "s"}
            </>
          ) : (
            <span className="text-slate-300">no candidates this run</span>
          )}
          {scanMeta.status === "HALTED" ? " · macro HALT" : ""}
        </span>
      </div>
    </Card>
  );
}
