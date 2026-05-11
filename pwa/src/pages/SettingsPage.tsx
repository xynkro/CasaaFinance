import { useState } from "react";
import type { Settings } from "../settings";
import type { ApiUsageRow } from "../data";
import { ApiUsageCard } from "../cards/ApiUsageCard";
import { LogOut, DollarSign, LayoutGrid, Home, Sun, Type, Layers, Droplets, Smartphone, ArrowUpFromLine, ArrowDownFromLine, Copy, Check, Clock, Eye, CheckCircle, XCircle, AlertTriangle, Info, Zap, Hourglass } from "lucide-react";

const TAB_NAMES = ["Home", "Portfolio", "Options", "Decisions", "Review", "Settings"];

const ACCENT_COLORS: { key: Settings["accentColor"]; hex: string; label: string }[] = [
  { key: "bloomberg",      hex: "#ff8c00", label: "Bloomberg" },
  { key: "terminal_green", hex: "#27d57f", label: "Terminal" },
  { key: "indigo",         hex: "#818cf8", label: "Indigo" },
  { key: "emerald",        hex: "#34d399", label: "Emerald" },
  { key: "amber",          hex: "#fbbf24", label: "Amber" },
  { key: "pink",           hex: "#f472b6", label: "Pink" },
  { key: "cyan",           hex: "#22d3ee", label: "Cyan" },
];

const FONT_PRESETS: { px: number; label: string }[] = [
  { px: 14, label: "Compact" },
  { px: 16, label: "Comfortable" },
  { px: 18, label: "Large" },
  { px: 20, label: "Extra Large" },
];

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={`relative w-11 h-6 rounded-full transition-colors ${
        on ? "bg-indigo-500" : "bg-slate-600"
      }`}
    >
      <div
        className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-5" : ""
        }`}
      />
    </button>
  );
}

function Slider({
  value,
  min,
  max,
  step,
  onChange,
  label,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  label?: string;
}) {
  return (
    <div className="flex items-center gap-3 w-40">
      <input
        type="range"
        min={min}
        max={max}
        step={step ?? 1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none bg-slate-600 accent-indigo-500 cursor-pointer"
      />
      {label && <span className="text-[length:var(--t-xs)] text-slate-400 tabular-nums w-8 text-right shrink-0">{label}</span>}
    </div>
  );
}

function SettingRow({
  icon: Icon,
  label,
  description,
  children,
}: {
  icon: React.ComponentType<{ size: number; className?: string }>;
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-3.5">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-8 h-8 rounded-lg bg-slate-700/50 flex items-center justify-center shrink-0">
          <Icon size={16} className="text-slate-400" />
        </div>
        <div className="min-w-0">
          <div className="text-[length:var(--t-sm)] font-semibold text-slate-100">{label}</div>
          {description && <div className="text-[length:var(--t-xs)] text-slate-400 mt-0.5">{description}</div>}
        </div>
      </div>
      <div className="shrink-0 ml-3">{children}</div>
    </div>
  );
}

function BuildChip() {
  const build = (import.meta.env.VITE_BUILD as string | undefined) || "dev";
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(build);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard API can be unavailable on http or older iOS — silently ignore.
    }
  };

  return (
    <div className="flex justify-center mt-2">
      <button
        onClick={handleCopy}
        className="glass flex items-center gap-2.5 px-3.5 py-2 rounded-full border border-white/10 hover:border-white/20 active:scale-95 transition-all"
        aria-label={`Copy build hash ${build}`}
      >
        <span className="text-[length:var(--t-2xs)] font-medium tracking-[0.12em] text-slate-400 uppercase">Build</span>
        <span className="text-[length:var(--t-xs)] font-mono font-semibold text-slate-100 tabular-nums">{build}</span>
        {copied ? (
          <Check size={12} className="text-emerald-400" />
        ) : (
          <Copy size={12} className="text-slate-500" />
        )}
      </button>
    </div>
  );
}

/**
 * Decision Status Glossary — explains the 5 status values the brain
 * emits on every decision_queue row. Shown in Settings as a reference
 * card so a new user (or a future-you who forgot) can decode the
 * Decisions tab without context-switching to the prompt source.
 *
 * Status values are kept in sync with `prompts/cron_wsr_full.md` §6c
 * "Status values" comment block. If a new status is added there,
 * update this glossary too.
 */
function DecisionStatusGlossary() {
  const items: Array<{
    icon: React.ComponentType<{ size?: number; className?: string }>;
    label: string;
    color: string;
    bg: string;
    short: string;
    body: string;
  }> = [
    {
      icon: Clock,
      label: "Pending",
      color: "#fbbf24",
      bg: "rgba(251,191,36,0.10)",
      short: "Actionable this week",
      body:
        "The brain wants you to ACT on this row in the next few days. " +
        "Entry zone is live, capital fits the exposure cap, and the " +
        "thesis is intact. Pending share entries usually carry a " +
        '"buy now" tranche in the Accumulation panel; pending option ' +
        "entries are CSPs or CCs the brain wants written this cycle.",
    },
    {
      icon: Eye,
      label: "Watching",
      color: "#60a5fa",
      bg: "rgba(96,165,250,0.10)",
      short: "Awaiting trigger — don't act yet",
      body:
        "The thesis is valid but a precondition isn't met yet. Could be " +
        "a price level (\"100sh @ $155 LMT when SPY pulls back\"), a " +
        "regime gate (\"on NEW_ENTRY_ALLOWED\"), an event (\"after AMD " +
        "Q1 earnings 5/13\"), or a confirmation (\"on TV daily=BUY\"). " +
        "Read the accumulation plan for the exact trigger. No capital " +
        "is allocated until something flips it to Pending. " +
        "While Watching, the card may show one of three derived pills " +
        "(Close / Ready / ACT NOW) — see below.",
    },
    {
      icon: CheckCircle,
      label: "Filled",
      color: "#34d399",
      bg: "rgba(52,211,153,0.10)",
      short: "Already executed — managing now",
      body:
        "You already wrote the option or bought the shares; this row is " +
        "the brain's mid-cycle thesis update. For options, the plan " +
        'describes EXIT/MANAGEMENT ("let expire | roll +14d on -2% | ' +
        'close at 50% profit"). Mid-week WSR Lite re-emits Filled rows ' +
        "with refreshed proximity / IV / DTE context.",
    },
    {
      icon: XCircle,
      label: "Killed",
      color: "#f87171",
      bg: "rgba(248,113,113,0.10)",
      short: "Thesis broken — do not act",
      body:
        'The brain explicitly retracted this idea. Reasons vary: anchor ' +
        "support broke, fundamentals changed (earnings miss / " +
        "downgrade), regime shifted into CASH_PRIORITY, or a sizing " +
        "constraint made it infeasible. Killed rows stay visible for " +
        "audit (so you can see what was on the table and why it died) " +
        "but the PWA filters them out of the active Pending/Watching " +
        "lists.",
    },
    {
      icon: AlertTriangle,
      label: "Expired",
      color: "#94a3b8",
      bg: "rgba(148,163,184,0.10)",
      short: "DTE elapsed without action",
      body:
        "Option DTE passed and the position resolved on its own (let " +
        "expire worthless / assigned). Or a watching share entry sat " +
        "past its time stop without triggering. Historical only — the " +
        "Review tab shows expired rows in the closed-decisions roll-up " +
        "so you can audit hit rate.",
    },
  ];

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider">
          Decision Status Glossary
        </h3>
        <Info size={14} className="text-slate-600" />
      </div>
      <p className="text-[length:var(--t-xs)] text-slate-500 mb-4 leading-relaxed">
        Every row in the Decisions tab carries one of five status values.
        The brain (Opus, on Mon/Wed/Fri/Sun crons) sets the status when
        it writes the row; you don't change it manually.
      </p>
      <div className="flex flex-col gap-3">
        {items.map((it) => {
          const Icon = it.icon;
          return (
            <div
              key={it.label}
              className="rounded-xl p-3"
              style={{ background: it.bg, border: `1px solid ${it.color}22` }}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <div
                  className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                  style={{ background: `${it.color}1a`, color: it.color }}
                >
                  <Icon size={14} />
                </div>
                <span
                  className="text-[length:var(--t-sm)] font-bold uppercase tracking-wide"
                  style={{ color: it.color }}
                >
                  {it.label}
                </span>
                <span className="text-[length:var(--t-xs)] text-slate-400">
                  — {it.short}
                </span>
              </div>
              <p className="text-[length:var(--t-xs)] text-slate-400 leading-relaxed pl-9">
                {it.body}
              </p>
            </div>
          );
        })}
      </div>

      {/* Derived "bridge" states — what fills the gap between Watching
          and Filled. The brain's status field is sticky for 2-3 days
          between WSR runs; these are computed CLIENT-SIDE every time
          the PWA refreshes from live price + regime + TV signals so
          you see "ACT NOW" in real time. Renders as a small pill in
          the Decisions card header next to the status pill. */}
      <div className="mt-5 pt-5 border-t border-white/5">
        <div className="flex items-center gap-2 mb-3">
          <Zap size={12} className="text-red-400" />
          <h4 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider">
            Watching — derived states
          </h4>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 mb-3 leading-relaxed">
          A Watching row's trigger is checked LIVE every PWA refresh.
          Three small pills surface based on how close the trigger is to
          firing — without waiting for the next WSR re-emission:
        </p>
        <div className="flex flex-col gap-2.5">
          {[
            {
              icon: Hourglass,
              color: "#fcd34d",
              bg: "rgba(251,191,36,0.10)",
              label: "Close",
              body:
                "Live price within 3% of the brain's trigger level. " +
                "Heads-up — start watching this one closely.",
            },
            {
              icon: Hourglass,
              color: "#93c5fd",
              bg: "rgba(96,165,250,0.12)",
              label: "Ready (gated)",
              body:
                "Price trigger is HIT, but a gate (regime " +
                "= NEW_ENTRY_ALLOWED, TV daily = BUY, etc.) is still " +
                "blocking. The card tooltip shows which gate.",
            },
            {
              icon: Zap,
              color: "#fca5a5",
              bg: "rgba(239,68,68,0.15)",
              label: "ACT NOW",
              body:
                "Price trigger HIT and all gates clear. Pulsing red — " +
                "the conditions the brain set are met right now. Open " +
                "IBKR and execute per the accumulation plan.",
            },
          ].map((it) => {
            const Icon = it.icon;
            return (
              <div
                key={it.label}
                className="flex items-start gap-2 rounded-lg p-2.5"
                style={{ background: it.bg, border: `1px solid ${it.color}22` }}
              >
                <span
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold uppercase tracking-wide shrink-0"
                  style={{
                    background: `${it.color}18`,
                    border: `1px solid ${it.color}33`,
                    color: it.color,
                  }}
                >
                  <Icon size={10} />
                  {it.label}
                </span>
                <span className="text-[length:var(--t-xs)] text-slate-400 leading-relaxed">
                  {it.body}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Strategy types — what each STRATEGY token in decision_queue means.
          Important: "HOLD" doesn't appear here as a strategy. It's a
          recommendation verb that means "don't act today", not a trade
          structure. See Exit Plan recommendations below for that. */}
      <div className="mt-5 pt-5 border-t border-white/5">
        <div className="flex items-center gap-2 mb-3">
          <Info size={12} className="text-emerald-400" />
          <h4 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider">
            Strategy types
          </h4>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 mb-3 leading-relaxed">
          The <code className="text-slate-300">strategy</code> column on each
          decision is the trade STRUCTURE, not whether to act today (that's
          the status pill). These are the strategies the brain selects from:
        </p>
        <div className="flex flex-col gap-2.5">
          {[
            {
              label: "BUY_DIP",
              color: "#34d399",
              bg: "rgba(52,211,153,0.10)",
              body:
                "Buy shares outright at the entry price. The simplest " +
                "long entry — usually accumulation tranches into a " +
                "compounder or a tactical pullback play. Cash account, no leverage.",
            },
            {
              label: "TRIM",
              color: "#fbbf24",
              bg: "rgba(251,191,36,0.10)",
              body:
                "Sell PART of an existing position (typically 1/3 or 1/2). " +
                "Fired on T1_HIT, on RP overweight, or when confluence " +
                "shifts negative (e.g. 2+ Congress sells inside 30d). " +
                "NOT a full exit — it's risk-reduction.",
            },
            {
              label: "CSP",
              color: "#60a5fa",
              bg: "rgba(96,165,250,0.10)",
              body:
                "Cash-Secured Put. SELL a put at strike X — collect " +
                "premium, get assigned at X-premium if price drops. Used " +
                "to acquire wheel-stocks at a discount OR pure premium-harvest " +
                "on stocks we'd be OK to own. Gated by TV signal + analyst " +
                "consensus — won't fire on STRONG_SELL or HOLD-consensus names.",
            },
            {
              label: "CC",
              color: "#a78bfa",
              bg: "rgba(167,139,250,0.10)",
              body:
                "Covered Call. SELL a call against shares we hold — caps " +
                "upside in exchange for premium. Used on stagnating positions, " +
                "bag-managing positions (BBAI/BTBT-style), or as the second " +
                "leg of a wheel post-CSP assignment. Blocked on core/blue_chip " +
                "buckets (don't cap a compounder) and on STRONG_BUY signals.",
            },
            {
              label: "LONG_CALL",
              color: "#f472b6",
              bg: "rgba(244,114,182,0.10)",
              body:
                "BUY a call — directional bullish bet with capped downside " +
                "(premium = max loss). Used by gov_confluence when score ≥ 80 " +
                "for a Tier-B signal. Brain picks delta (0.50 / 0.60) and " +
                "DTE (30-45d) at brief time. Higher conviction than BUY_DIP " +
                "because we're paying for leverage.",
            },
            {
              label: "PMCC",
              color: "#fb923c",
              bg: "rgba(251,146,60,0.10)",
              body:
                "Poor Man's Covered Call. Long deep-ITM LEAPS call + short " +
                "near-term OTM call against it. Capital-efficient way to " +
                "wheel a name without owning 100 shares. Used at score 90+ " +
                "when IV is also elevated.",
            },
            {
              label: "LONG_PUT",
              color: "#f87171",
              bg: "rgba(248,113,113,0.10)",
              body:
                "BUY a put — bearish bet OR hedge on an existing long. " +
                "Currently rarely fires (book is long-only) but exists in " +
                "the schema for future short/hedge ideas.",
            },
          ].map((it) => (
            <div
              key={it.label}
              className="rounded-lg p-2.5"
              style={{ background: it.bg, border: `1px solid ${it.color}22` }}
            >
              <span
                className="inline-block px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold uppercase tracking-wide mb-1"
                style={{
                  background: `${it.color}18`,
                  border: `1px solid ${it.color}33`,
                  color: it.color,
                }}
              >
                {it.label}
              </span>
              <p className="text-[length:var(--t-xs)] text-slate-400 leading-relaxed">
                {it.body}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Exit Plan / Action Queue verbs — what HOLD, EXIT, WARNING etc.
          mean on the Action Queue and Exit Plan cards. This is the
          section the user keeps asking about because "HOLD" and "EXIT"
          look like trade commands but they're actually position-status
          read-outs from exit_plans, NOT new orders to place. */}
      <div className="mt-5 pt-5 border-t border-white/5">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={12} className="text-amber-400" />
          <h4 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider">
            Action Queue / Exit Plan verbs
          </h4>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 mb-3 leading-relaxed">
          These appear on the Action Queue and on the Exit Plan column of
          a position. They describe what the system thinks about a
          position you ALREADY hold — NOT a new trade to place. The
          status (HEALTHY / WARNING / BAG / etc.) is the system's read
          on the position; the recommendation (HOLD / EXIT / TRIM) is
          the suggested response.
        </p>
        <div className="flex flex-col gap-2.5">
          {[
            {
              label: "HEALTHY",
              color: "#34d399",
              bg: "rgba(52,211,153,0.10)",
              body:
                "Price is comfortably above stop, no targets hit yet. " +
                "Nothing to do — let it run. Default state for any " +
                "position with positive trajectory.",
            },
            {
              label: "T1_HIT",
              color: "#a7f3d0",
              bg: "rgba(167,243,208,0.10)",
              body:
                "Price reached target_1. For BLUE-CHIP / ETF positions: " +
                "the recommendation is LET WINNER RUN — don't sell. For " +
                "speculative names: the rec is TRIM 1/3, raise stop to " +
                "breakeven. NOT an exit signal — it's the first profit checkpoint.",
            },
            {
              label: "T2_HIT",
              color: "#86efac",
              bg: "rgba(134,239,172,0.10)",
              body:
                "Price reached target_2 (Fib 1.382 extension or T1 + 2×ATR). " +
                "Recommendation is TRIM / TRAIL — take more profit or " +
                "tighten the stop to T1. Strong positive outcome.",
            },
            {
              label: "WARNING",
              color: "#fbbf24",
              bg: "rgba(251,191,36,0.10)",
              body:
                "Within 3% of stop_loss, OR price has broken below SMA-50/200. " +
                "Recommendation is HOLD WITH CAUTION. Doesn't mean exit — " +
                "means re-read the thesis and prepare for a stop trigger.",
            },
            {
              label: "STOP_TRIGGERED",
              color: "#f87171",
              bg: "rgba(248,113,113,0.10)",
              body:
                "Live price has crossed below stop_loss. Recommendation " +
                "is EXIT — honor the stop or revise the thesis with a new stop " +
                "level. Letting losers run past the stop is what turns -19% " +
                "into -40%.",
            },
            {
              label: "BAG",
              color: "#f43f5e",
              bg: "rgba(244,63,94,0.10)",
              body:
                "Already past the percentage hard stop (-25% by default, " +
                "-30% for speculatives, -10% for blue-chip). Position is " +
                "too far underwater for a clean exit. Recommendation: if " +
                "wheeling (CC at breakeven+), manage through assignment; " +
                "if not wheeling, take the L and free the capital.",
            },
            {
              label: "CATALYST_WARNING",
              color: "#fb923c",
              bg: "rgba(251,146,60,0.10)",
              body:
                "Position has an earnings event / FDA decision / Fed " +
                "minute inside the option DTE. Recommendation: consider " +
                "closing the option pre-event. Binary catalysts can negate " +
                "all the IV-decay math.",
            },
            {
              label: "TIME_STOP",
              color: "#94a3b8",
              bg: "rgba(148,163,184,0.10)",
              body:
                "Position has been held longer than time_stop_days (45 " +
                "default) without reaching T1. Recommendation: REASSESS " +
                "the thesis. Stale positions waste capital that could be " +
                "compounding elsewhere.",
            },
          ].map((it) => (
            <div
              key={it.label}
              className="rounded-lg p-2.5"
              style={{ background: it.bg, border: `1px solid ${it.color}22` }}
            >
              <span
                className="inline-block px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold uppercase tracking-wide mb-1"
                style={{
                  background: `${it.color}18`,
                  border: `1px solid ${it.color}33`,
                  color: it.color,
                }}
              >
                {it.label}
              </span>
              <p className="text-[length:var(--t-xs)] text-slate-400 leading-relaxed">
                {it.body}
              </p>
            </div>
          ))}
        </div>

        {/* Disambiguation card — directly addresses the "HOLD on a Buy
            Ideas card" confusion. */}
        <div className="mt-4 rounded-lg p-3" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}>
          <p className="text-[length:var(--t-2xs)] text-slate-400 leading-relaxed">
            <strong className="text-slate-200">Why "HOLD" can be confusing:</strong>{" "}
            "HOLD" on a position you already own means <em>keep what you have,
            no new action</em>. "HOLD" on an idea you don't yet own means{" "}
            <em>don't buy yet — preconditions not met</em>. Same word, opposite
            implication. The card label tells you which: Action Queue / Exit
            Plan = position status; Watching / Fresh Ideas = entry status.
          </p>
        </div>
      </div>
    </div>
  );
}

export function SettingsPage({
  settings,
  onUpdate,
  onLogout,
  apiUsage,
}: {
  settings: Settings;
  onUpdate: (patch: Partial<Settings>) => void;
  onLogout: () => void;
  apiUsage?: ApiUsageRow[];
}) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      {/* Accent color */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider mb-3">Accent Color</h3>
        <div className="flex items-center gap-2 flex-wrap">
          {ACCENT_COLORS.map((c) => (
            <button
              key={c.key}
              onClick={() => onUpdate({ accentColor: c.key })}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl border transition-all ${
                settings.accentColor === c.key
                  ? "bg-white/10 border-white/25"
                  : "bg-white/3 border-white/5 hover:border-white/15"
              }`}
            >
              <div className="w-4 h-4 rounded-full shadow-lg" style={{ background: c.hex, boxShadow: `0 0 10px ${c.hex}66` }} />
              <span className="text-[length:var(--t-xs)] font-medium text-slate-200">{c.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Layout — safe area */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider mb-2">Layout & Safe Area</h3>
        <div className="divide-y divide-white/5">
          <SettingRow icon={Smartphone} label="Ignore iOS safe area" description="Use custom padding instead">
            <Toggle on={settings.ignoreSafeArea} onToggle={() => onUpdate({ ignoreSafeArea: !settings.ignoreSafeArea })} />
          </SettingRow>

          {settings.ignoreSafeArea && (
            <>
              <SettingRow icon={ArrowUpFromLine} label="Top padding" description="Space above header">
                <Slider value={settings.safeAreaTop} min={0} max={60} onChange={(v) => onUpdate({ safeAreaTop: v })} label={`${settings.safeAreaTop}px`} />
              </SettingRow>

              <SettingRow icon={ArrowDownFromLine} label="Bottom padding" description="Space below tab bar">
                <Slider value={settings.safeAreaBottom} min={0} max={60} onChange={(v) => onUpdate({ safeAreaBottom: v })} label={`${settings.safeAreaBottom}px`} />
              </SettingRow>
            </>
          )}

          <SettingRow icon={LayoutGrid} label="Tab bar height" description="Size of the bottom nav">
            <Slider value={settings.tabBarHeight} min={48} max={80} onChange={(v) => onUpdate({ tabBarHeight: v })} label={`${settings.tabBarHeight}px`} />
          </SettingRow>
        </div>
      </div>

      {/* Appearance */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider mb-2">Appearance</h3>
        <div className="divide-y divide-white/5">
          <SettingRow icon={Sun} label="Background darkness" description="Darken the background image">
            <Slider value={settings.bgDarkness} min={20} max={95} onChange={(v) => onUpdate({ bgDarkness: v })} label={`${settings.bgDarkness}%`} />
          </SettingRow>

          <SettingRow icon={Droplets} label="Extra blur" description="Additional background blur">
            <Slider value={settings.bgBlur} min={0} max={30} onChange={(v) => onUpdate({ bgBlur: v })} label={`${settings.bgBlur}px`} />
          </SettingRow>

          <SettingRow icon={Layers} label="Card opacity" description="Glass card transparency">
            <Slider value={settings.cardOpacity} min={10} max={100} onChange={(v) => onUpdate({ cardOpacity: v })} label={`${settings.cardOpacity}%`} />
          </SettingRow>

          <SettingRow icon={Type} label="Font size" description="Scales the entire UI">
            <Slider value={settings.fontSize} min={12} max={22} onChange={(v) => onUpdate({ fontSize: v })} label={`${settings.fontSize}px`} />
          </SettingRow>
          <div className="pb-3.5 -mt-1">
            <div className="flex items-center gap-1.5 flex-wrap pl-11">
              {FONT_PRESETS.map((p) => {
                const active = settings.fontSize === p.px;
                return (
                  <button
                    key={p.px}
                    onClick={() => onUpdate({ fontSize: p.px })}
                    className={`px-2.5 py-1 rounded-lg border transition-all text-[length:var(--t-2xs)] font-medium tabular-nums ${
                      active
                        ? "bg-white/10 border-white/25 text-slate-100"
                        : "bg-white/3 border-white/5 text-slate-400 hover:border-white/15"
                    }`}
                  >
                    {p.label} <span className="opacity-60">{p.px}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Display */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider mb-2">Display</h3>
        <div className="divide-y divide-white/5">
          <SettingRow icon={DollarSign} label="Currency" description="How values are shown">
            <select
              value={settings.currency}
              onChange={(e) => onUpdate({ currency: e.target.value as Settings["currency"] })}
              className="bg-slate-700/50 text-[length:var(--t-sm)] text-slate-200 rounded-lg px-3 py-1.5 border border-white/10 outline-none focus:border-indigo-500"
            >
              <option value="USD">USD only</option>
              <option value="SGD">SGD only</option>
              <option value="both">Both</option>
            </select>
          </SettingRow>

          <SettingRow icon={Home} label="Default tab" description="Tab shown on launch">
            <select
              value={settings.defaultTab}
              onChange={(e) => onUpdate({ defaultTab: Number(e.target.value) })}
              className="bg-slate-700/50 text-[length:var(--t-sm)] text-slate-200 rounded-lg px-3 py-1.5 border border-white/10 outline-none focus:border-indigo-500"
            >
              {TAB_NAMES.map((name, i) => (
                <option key={name} value={i}>{name}</option>
              ))}
            </select>
          </SettingRow>
        </div>
      </div>

      {/* Reference glossary — what the 5 decision_queue status values mean */}
      <DecisionStatusGlossary />

      {/* Anthropic API spend across brain workflows. Empty-state when
          api_usage sheet hasn't been populated yet. */}
      <ApiUsageCard rows={apiUsage ?? []} />

      {/* Account */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-[length:var(--t-xs)] font-medium text-slate-300 uppercase tracking-wider mb-2">Account</h3>
        <button
          onClick={onLogout}
          className="flex items-center gap-3 w-full py-3 text-red-400 hover:text-red-300 transition-colors"
        >
          <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
            <LogOut size={16} />
          </div>
          <span className="text-[length:var(--t-sm)] font-medium">Lock app</span>
        </button>
      </div>

      <BuildChip />
    </div>
  );
}
