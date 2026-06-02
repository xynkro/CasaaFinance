import type { AlpacaSnapshotRow, AlpacaPositionRow, ParsedOcc, PaperBenchmarkRow } from "../data";
import { parseOcc } from "../data";
import { Card } from "./Card";
import { FlaskConical, TrendingUp, TrendingDown, Bot, Swords } from "lucide-react";

/* ── helpers ─────────────────────────────────────────────────────────── */

const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function money(v: number, dp = 2): string {
  if (!isFinite(v)) return "—";
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })}`;
}

function fmtExpiry(iso: string): string {
  const [, m, d] = (iso || "").split("-").map(Number);
  if (!m || !d) return iso;
  return `${SHORT_MONTHS[m - 1]} ${d}`;
}

const num = (s: string | number | undefined) => {
  const n = Number(s);
  return isFinite(n) ? n : 0;
};

/* Per-strategy accent (matches ScanResultsCard conventions). */
const STRAT_ACCENT: Record<string, string> = {
  CSP: "text-amber-400", CC: "text-blue-400", PCS: "text-violet-400",
  CCS: "text-rose-400", IC: "text-cyan-400", PMCC: "text-emerald-400",
  LONG_CALL: "text-lime-400", LONG_PUT: "text-orange-400", STOCK: "text-slate-300",
  SPREAD: "text-slate-300",
};

interface Leg {
  parsed: ParsedOcc | null;
  qty: number;
  avgCost: number;
  upl: number;
  mktVal: number;
  raw: AlpacaPositionRow;
}

interface PosGroup {
  key: string;
  underlying: string;
  expiry: string | null;
  isOption: boolean;
  legs: Leg[];
  strategy: string;
  upl: number;
  netCredit: number;     // >0 = credit collected at entry
}

function inferStrategy(legs: Leg[]): string {
  if (legs.some((l) => !l.parsed)) return "STOCK";
  const puts = legs.filter((l) => l.parsed!.right === "P");
  const calls = legs.filter((l) => l.parsed!.right === "C");
  if (legs.length === 1) {
    const l = legs[0];
    const isPut = l.parsed!.right === "P";
    if (l.qty < 0) return isPut ? "CSP" : "CC";
    return isPut ? "LONG_PUT" : "LONG_CALL";
  }
  if (legs.length === 2 && puts.length === 2) return "PCS";
  if (legs.length === 2 && calls.length === 2) return "CCS";
  if (legs.length === 4 && puts.length === 2 && calls.length === 2) return "IC";
  return "SPREAD";
}

/** Group option legs by underlying+expiry; equities stand alone. */
function groupPositions(positions: AlpacaPositionRow[]): PosGroup[] {
  const groups = new Map<string, Leg[]>();
  for (const p of positions) {
    const parsed = parseOcc(p.ticker);
    const leg: Leg = {
      parsed,
      qty: num(p.qty),
      avgCost: num(p.avg_cost),
      upl: num(p.upl),
      mktVal: num(p.mkt_val),
      raw: p,
    };
    const key = parsed ? `${parsed.underlying}|${parsed.expiry}` : `EQ|${p.ticker}`;
    (groups.get(key) ?? groups.set(key, []).get(key)!).push(leg);
  }

  const out: PosGroup[] = [];
  for (const [key, legs] of groups) {
    legs.sort((a, b) => (b.parsed?.strike ?? 0) - (a.parsed?.strike ?? 0));
    const first = legs[0];
    const netCredit = legs.reduce(
      (s, l) => s + (l.qty < 0 ? 1 : -1) * l.avgCost * Math.abs(l.qty) * 100, 0);
    out.push({
      key,
      underlying: first.parsed?.underlying ?? first.raw.ticker,
      expiry: first.parsed?.expiry ?? null,
      isOption: !!first.parsed,
      legs,
      strategy: inferStrategy(legs),
      upl: legs.reduce((s, l) => s + l.upl, 0),
      netCredit,
    });
  }
  return out.sort((a, b) => a.upl - b.upl);
}

function contractLabel(g: PosGroup): string {
  if (!g.isOption) {
    const q = g.legs[0].qty;
    return `${q} sh`;
  }
  const puts = g.legs.filter((l) => l.parsed!.right === "P").map((l) => l.parsed!.strike);
  const calls = g.legs.filter((l) => l.parsed!.right === "C").map((l) => l.parsed!.strike);
  const parts: string[] = [];
  if (puts.length) parts.push(`${puts.map((s) => s).join("/")}P`);
  if (calls.length) parts.push(`${calls.map((s) => s).join("/")}C`);
  return parts.join(" · ");
}

/* ── position group row ──────────────────────────────────────────────── */

function GroupRow({ g }: { g: PosGroup }) {
  const positive = g.upl >= 0;
  const pctCaptured = g.netCredit > 0 ? (g.upl / g.netCredit) * 100 : null;
  const accent = STRAT_ACCENT[g.strategy] ?? "text-slate-300";

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/5 last:border-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-[length:var(--t-2xs)] font-bold ${accent}`}>{g.strategy}</span>
          <span className="text-[length:var(--t-sm)] font-bold text-white">{g.underlying}</span>
          {g.expiry && (
            <span className="text-[length:var(--t-2xs)] text-slate-500">{fmtExpiry(g.expiry)}</span>
          )}
        </div>
        <div className="text-[length:var(--t-2xs)] text-slate-400 tabular-nums mt-0.5">
          {contractLabel(g)}
          {g.netCredit > 0 && (
            <span className="text-slate-600"> · {money(g.netCredit, 0)} credit</span>
          )}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className={`text-[length:var(--t-sm)] font-semibold tabular-nums flex items-center justify-end gap-1 ${positive ? "text-emerald-400" : "text-red-400"}`}>
          {positive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
          {g.upl >= 0 ? "+" : ""}{money(g.upl)}
        </div>
        {pctCaptured !== null && (
          <div className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
            {pctCaptured >= 0 ? "+" : ""}{pctCaptured.toFixed(0)}% of credit
          </div>
        )}
      </div>
    </div>
  );
}

/* ── main view ───────────────────────────────────────────────────────── */

/* ── SPY benchmark strip — the honest "are we beating the index?" line ── */

function BenchmarkStrip({ benchmark }: { benchmark: PaperBenchmarkRow[] }) {
  const total = benchmark.find((b) => b.ticker === "TOTAL");
  if (!total) return null;
  const bookPl = num(total.position_pl);
  const spyPl = num(total.spy_equiv_pl);
  const alpha = num(total.alpha_pl);
  const beating = alpha >= 0;
  const legs = benchmark.filter((b) => b.ticker !== "TOTAL");
  const won = legs.filter((b) => (b.beat_spy || "").toUpperCase() === "TRUE").length;

  return (
    <div className={`rounded-2xl border px-3.5 py-3 ${beating ? "border-emerald-500/30 bg-emerald-500/[0.07]" : "border-red-500/30 bg-red-500/[0.07]"}`}>
      <div className="flex items-center gap-2 mb-2">
        <Swords size={14} className={beating ? "text-emerald-400" : "text-red-400"} />
        <h3 className="text-[length:var(--t-xs)] font-bold text-slate-200">vs Buy-and-Hold SPY</h3>
        <span className={`ml-auto text-[length:var(--t-2xs)] font-bold px-1.5 py-0.5 rounded ${beating ? "text-emerald-300 bg-emerald-500/15" : "text-red-300 bg-red-500/15"}`}>
          {beating ? "BEATING" : "LAGGING"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">Book P&L</div>
          <div className="text-[length:var(--t-sm)] font-bold text-white tabular-nums">{bookPl >= 0 ? "+" : ""}{money(bookPl, 0)}</div>
        </div>
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">SPY would've</div>
          <div className="text-[length:var(--t-sm)] text-slate-300 tabular-nums">{spyPl >= 0 ? "+" : ""}{money(spyPl, 0)}</div>
        </div>
        <div>
          <div className="text-[length:var(--t-2xs)] text-slate-600">Alpha</div>
          <div className={`text-[length:var(--t-sm)] font-bold tabular-nums ${beating ? "text-emerald-400" : "text-red-400"}`}>
            {alpha >= 0 ? "+" : ""}{money(alpha, 0)}
          </div>
        </div>
      </div>
      <div className="text-[length:var(--t-2xs)] text-slate-500 mt-1.5">
        {won}/{legs.length} positions beat SPY over their hold · the burden of proof is on the active book.
      </div>
    </div>
  );
}

export function PaperTradingView({
  snapshot,
  positions,
  benchmark,
  loading,
}: {
  snapshot: AlpacaSnapshotRow | null;
  positions: AlpacaPositionRow[];
  benchmark: PaperBenchmarkRow[];
  loading: boolean;
}) {
  // This Alpaca account is shared with another bot (ZeroDTE 0-DTE SPY). Show
  // ONLY FinancePWA's own book — positions its casaa- executor placed — so the
  // view isn't polluted by trades it didn't make.
  const owned = positions.filter((p) => (p.origin ?? "casaa") !== "external");
  const externalCount = positions.length - owned.length;
  const groups = groupPositions(owned);
  const totalUpl = groups.reduce((s, g) => s + g.upl, 0);
  const nlv = num(snapshot?.net_liq);
  const cash = num(snapshot?.cash);
  const bp = num(snapshot?.buying_power);

  return (
    <div className="flex flex-col gap-3">
      {/* UNMISTAKABLE paper banner — this is never real money */}
      <div className="rounded-2xl border border-dashed border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5 flex items-center gap-2.5">
        <FlaskConical size={16} className="text-amber-400 shrink-0" />
        <div className="leading-tight">
          <div className="text-[length:var(--t-xs)] font-bold text-amber-300 tracking-wide">
            PAPER TRADING · ALPACA
          </div>
          <div className="text-[length:var(--t-2xs)] text-amber-200/60">
            Simulated money. Auto-executes the scanner's picks to measure real-fill edge.
          </div>
        </div>
      </div>

      {/* The honest scoreboard — is the active book beating the index? */}
      <BenchmarkStrip benchmark={benchmark} />

      {/* Paper account summary */}
      <Card variant="accent">
        {loading && !snapshot ? (
          <div className="space-y-2">
            <div className="shimmer h-4 w-28" />
            <div className="shimmer h-8 w-40" />
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Bot size={14} className="text-amber-400" />
                <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Auto-Trader Account</h2>
              </div>
              {snapshot?.date && (
                <time className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">
                  {snapshot.date.slice(0, 10)}
                </time>
              )}
            </div>
            <div className="grid grid-cols-4 gap-2">
              <div>
                <div className="text-[length:var(--t-2xs)] text-slate-600">NLV</div>
                <div className="text-[length:var(--t-sm)] font-bold text-white tabular-nums">{money(nlv, 0)}</div>
              </div>
              <div>
                <div className="text-[length:var(--t-2xs)] text-slate-600">Cash</div>
                <div className="text-[length:var(--t-sm)] text-slate-300 tabular-nums">{money(cash, 0)}</div>
              </div>
              <div>
                <div className="text-[length:var(--t-2xs)] text-slate-600">Buy Pwr</div>
                <div className="text-[length:var(--t-sm)] text-slate-300 tabular-nums">{money(bp, 0)}</div>
              </div>
              <div>
                <div className="text-[length:var(--t-2xs)] text-slate-600">Open P&L</div>
                <div className={`text-[length:var(--t-sm)] font-bold tabular-nums ${totalUpl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {totalUpl >= 0 ? "+" : ""}{money(totalUpl, 0)}
                </div>
              </div>
            </div>
          </>
        )}
      </Card>

      {/* Open auto-trader positions */}
      <Card>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-[length:var(--t-sm)] font-medium text-slate-300">Open Positions</h3>
          <span className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
            {groups.length} {groups.length === 1 ? "position" : "positions"}
          </span>
        </div>
        {externalCount > 0 && (
          <p className="text-[length:var(--t-2xs)] text-slate-600 -mt-0.5 mb-1.5">
            {externalCount} other position{externalCount === 1 ? "" : "s"} in this shared account
            (ZeroDTE / decision-queue) hidden — showing FinancePWA's book only.
          </p>
        )}
        {groups.length === 0 ? (
          <p className="text-[length:var(--t-xs)] text-slate-500 py-5 text-center">
            The auto-trader hasn't opened any paper positions yet.<br />
            <span className="text-slate-600">Picks are placed by <code className="text-slate-500">alpaca_paper_execute.py</code> on scan days.</span>
          </p>
        ) : (
          <div>
            {groups.map((g) => <GroupRow key={g.key} g={g} />)}
          </div>
        )}
      </Card>
    </div>
  );
}
