import { useState } from "react";
import type { UoaAlertRow } from "../data";
import { numeric } from "../data";
import { Card } from "./Card";
import { Activity, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from "lucide-react";

/* ── helpers ─────────────────────────────────────────────────────────── */

const SHORT_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function fmtExpiry(s: string | undefined): string {
  if (!s) return "";
  const parts = s.split("-").map(Number);
  if (parts.length !== 3) return s;
  const [, m, d] = parts;
  if (!m || !d || m < 1 || m > 12) return s;
  return `${SHORT_MONTHS[m - 1]} ${d}`;
}

function fmtNotional(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

/** Severity → icon + color config. */
function sevConfig(sev: number) {
  if (sev >= 3) return { icon: "🚨", bg: "bg-red-500/10 border-red-500/20", text: "text-red-400", label: "Extreme" };
  if (sev >= 2) return { icon: "🔥", bg: "bg-amber-500/10 border-amber-500/20", text: "text-amber-400", label: "Significant" };
  return { icon: "⚡", bg: "bg-sky-500/10 border-sky-500/20", text: "text-sky-400", label: "Notable" };
}

/** Alert type short label. */
const TYPE_LABEL: Record<string, string> = {
  VOL_OI_SPIKE: "Vol/OI",
  STRIKE_CONC: "Concentration",
  OTM_FLOW: "OTM Flow",
  PC_SKEW: "P/C Skew",
};

/** Moneyness color chip. */
function moneynessChip(m: string) {
  const styles: Record<string, string> = {
    ITM: "text-amber-400 bg-amber-500/10",
    ATM: "text-slate-300 bg-white/5",
    OTM: "text-sky-400 bg-sky-500/10",
    FAR_OTM: "text-violet-400 bg-violet-500/10",
  };
  const labels: Record<string, string> = {
    ITM: "ITM",
    ATM: "ATM",
    OTM: "OTM",
    FAR_OTM: "Far OTM",
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-medium ${styles[m] || "text-slate-500 bg-white/5"}`}>
      {labels[m] || m}
    </span>
  );
}

/* ── single alert row ────────────────────────────────────────────────── */

function AlertRow({ alert }: { alert: UoaAlertRow }) {
  const [expanded, setExpanded] = useState(false);
  const sev = numeric(alert.severity);
  const vol = numeric(alert.volume);
  const oi = numeric(alert.open_interest);
  const volOi = numeric(alert.vol_oi_ratio);
  const notional = numeric(alert.notional);
  const strike = numeric(alert.strike);
  const price = numeric(alert.underlying_last);
  const optPrice = numeric(alert.option_price);
  const iv = numeric(alert.implied_vol);
  const dte = numeric(alert.dte);
  const side = (alert.side || "").toUpperCase();
  const isCall = side === "CALL";
  const isPcSkew = alert.alert_type === "PC_SKEW";
  const sc = sevConfig(sev);

  // Directional lean — naive read based on side
  // CALL volume → lean bullish, PUT volume → lean bearish
  // PC_SKEW already has explicit direction in its detail text
  const DirectionIcon = isCall ? TrendingUp : TrendingDown;
  const dirColor = isCall ? "text-emerald-400" : "text-red-400";
  const dirLabel = isCall ? "Bullish" : "Bearish";
  const sideBg = isCall ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" : "bg-red-500/15 text-red-400 border-red-500/30";

  // OTM distance for context
  const otmPct = price > 0
    ? isCall
      ? ((strike - price) / price * 100)
      : ((price - strike) / price * 100)
    : 0;

  return (
    <div
      className={`rounded-xl border p-3 mb-2 cursor-pointer transition-colors ${sc.bg}`}
      onClick={() => setExpanded((e) => !e)}
    >
      {/* Header row */}
      <div className="flex items-center gap-2">
        <span className="text-[length:var(--t-sm)]">{sc.icon}</span>
        <span className="font-bold text-[length:var(--t-sm)] text-white">{alert.ticker}</span>

        {/* Side badge: CALL or PUT */}
        <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${sideBg}`}>
          {side}
        </span>

        {/* Direction lean icon */}
        <DirectionIcon size={13} className={dirColor} />

        <span className="ml-auto text-[length:var(--t-xs)] text-slate-400 font-mono">
          {fmtNotional(notional)}
        </span>
        {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </div>

      {/* Summary line */}
      <div className="flex items-center gap-2 mt-1 text-[length:var(--t-2xs)] text-slate-400 flex-wrap">
        {!isPcSkew && (
          <>
            <span className="font-mono text-white">${strike.toFixed(0)}{isCall ? "C" : "P"}</span>
            {optPrice > 0 && (
              <>
                <span>·</span>
                <span className="font-mono text-emerald-300">${optPrice < 1 ? optPrice.toFixed(2) : optPrice.toFixed(1)}</span>
              </>
            )}
            <span>·</span>
            <span>{fmtExpiry(alert.expiry)}</span>
            <span>·</span>
            <span>{dte}d</span>
            <span>·</span>
          </>
        )}
        <span className={`font-medium ${sc.text}`}>
          {TYPE_LABEL[alert.alert_type] || alert.alert_type}
        </span>
        {!isPcSkew && alert.moneyness && (
          <>
            <span>·</span>
            {moneynessChip(alert.moneyness)}
          </>
        )}
      </div>

      {/* Key stat: vol/OI or concentration */}
      <div className="mt-1.5 text-[length:var(--t-xs)] text-slate-300">
        {alert.alert_type === "VOL_OI_SPIKE" && (
          <span>
            <span className="font-bold text-white">{vol.toLocaleString()}</span>
            {" "}{isCall ? "calls" : "puts"} traded vs {oi.toLocaleString()} OI
            {volOi > 0 && <span className="text-slate-500"> ({volOi.toFixed(1)}x)</span>}
          </span>
        )}
        {alert.alert_type === "STRIKE_CONC" && (
          <span>{alert.detail}</span>
        )}
        {alert.alert_type === "OTM_FLOW" && (
          <span>
            <span className="font-bold text-white">{vol.toLocaleString()}</span>
            {" "}far-OTM {isCall ? "calls" : "puts"} ({Math.abs(otmPct).toFixed(0)}% away)
          </span>
        )}
        {alert.alert_type === "PC_SKEW" && (
          <span>{alert.detail}</span>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="mt-2 pt-2 border-t border-white/5 space-y-1.5 text-[length:var(--t-2xs)]">
          {!isPcSkew && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-400">
              <span>Underlying: <span className="text-white font-mono">${price.toFixed(2)}</span></span>
              {optPrice > 0 && (
                <span>Premium: <span className="text-emerald-300 font-mono">${optPrice < 1 ? optPrice.toFixed(2) : optPrice.toFixed(2)}/sh</span></span>
              )}
              <span>IV: <span className="text-white font-mono">{(iv * 100).toFixed(0)}%</span></span>
              <span>Volume: <span className="text-white font-mono">{vol.toLocaleString()}</span></span>
              <span>Open Int: <span className="text-white font-mono">{oi.toLocaleString()}</span></span>
              {otmPct !== 0 && (
                <span>Distance: <span className="text-white font-mono">{otmPct.toFixed(1)}% {otmPct > 0 ? "OTM" : "ITM"}</span></span>
              )}
            </div>
          )}
          <div className={`mt-1 px-2 py-1.5 rounded-lg ${isCall ? "bg-emerald-500/5" : "bg-red-500/5"}`}>
            <div className="flex items-center gap-1.5">
              <DirectionIcon size={12} className={dirColor} />
              <span className={`font-semibold ${dirColor}`}>Lean {dirLabel}</span>
            </div>
            <p className="text-slate-500 mt-0.5 text-[length:var(--t-2xs)]">
              {isCall
                ? "Call flow suggests upside interest. Could be directional buys or hedges against short positions."
                : "Put flow suggests downside interest. Could be protective hedges or directional bets."
              }
              {" "}Volume alone cannot distinguish buying from selling.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── main card ───────────────────────────────────────────────────────── */

export function UoaFlowCard({ alerts }: { alerts: UoaAlertRow[] }) {
  if (!alerts.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Activity size={14} className="text-violet-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Options Flow</h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          No unusual activity detected today.
        </p>
      </Card>
    );
  }

  // Sort by severity desc, then notional desc
  const sorted = [...alerts].sort((a, b) => {
    const sevDiff = numeric(b.severity) - numeric(a.severity);
    if (sevDiff !== 0) return sevDiff;
    return numeric(b.notional) - numeric(a.notional);
  });

  // Summary stats
  const callAlerts = alerts.filter((a) => a.side === "CALL").length;
  const putAlerts = alerts.filter((a) => a.side === "PUT").length;
  const totalNotional = alerts.reduce((s, a) => s + numeric(a.notional), 0);
  const extreme = alerts.filter((a) => numeric(a.severity) >= 3).length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-violet-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Options Flow</h2>
        </div>
        <span className="text-violet-400 text-[length:var(--t-2xs)] tabular-nums">
          {alerts.length} alerts
        </span>
      </div>

      {/* Summary strip */}
      <div className="flex gap-3 mb-3 text-[length:var(--t-2xs)]">
        <div className="flex items-center gap-1">
          <TrendingUp size={11} className="text-emerald-400" />
          <span className="text-emerald-400 font-medium">{callAlerts} calls</span>
        </div>
        <div className="flex items-center gap-1">
          <TrendingDown size={11} className="text-red-400" />
          <span className="text-red-400 font-medium">{putAlerts} puts</span>
        </div>
        <span className="text-slate-500">·</span>
        <span className="text-slate-400 font-mono">{fmtNotional(totalNotional)} total</span>
        {extreme > 0 && (
          <>
            <span className="text-slate-500">·</span>
            <span className="text-red-400">{extreme} extreme</span>
          </>
        )}
      </div>

      {/* Alert list */}
      <div>
        {sorted.map((a, i) => (
          <AlertRow key={`${a.ticker}-${a.strike}-${a.side}-${i}`} alert={a} />
        ))}
      </div>
    </Card>
  );
}
