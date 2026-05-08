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
