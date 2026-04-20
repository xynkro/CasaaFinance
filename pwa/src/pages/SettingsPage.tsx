import type { Settings } from "../settings";
import { LogOut, DollarSign, LayoutGrid, ListChecks, Home, Sun, Type, Layers, Droplets, Smartphone, ArrowUpFromLine, ArrowDownFromLine } from "lucide-react";

const TAB_NAMES = ["Home", "Portfolio", "Options", "Decisions", "Archive", "Settings"];

const ACCENT_COLORS: { key: Settings["accentColor"]; hex: string; label: string }[] = [
  { key: "indigo",  hex: "#818cf8", label: "Indigo" },
  { key: "emerald", hex: "#34d399", label: "Emerald" },
  { key: "amber",   hex: "#fbbf24", label: "Amber" },
  { key: "pink",    hex: "#f472b6", label: "Pink" },
  { key: "cyan",    hex: "#22d3ee", label: "Cyan" },
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
      {label && <span className="text-xs text-slate-400 tabular-nums w-8 text-right shrink-0">{label}</span>}
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
          <div className="text-sm font-semibold text-slate-100">{label}</div>
          {description && <div className="text-xs text-slate-400 mt-0.5">{description}</div>}
        </div>
      </div>
      <div className="shrink-0 ml-3">{children}</div>
    </div>
  );
}

export function SettingsPage({
  settings,
  onUpdate,
  onLogout,
}: {
  settings: Settings;
  onUpdate: (patch: Partial<Settings>) => void;
  onLogout: () => void;
}) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      {/* Accent color */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wider mb-3">Accent Color</h3>
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
              <span className="text-xs font-medium text-slate-200">{c.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Layout — safe area */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wider mb-2">Layout & Safe Area</h3>
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
        <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wider mb-2">Appearance</h3>
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

          <SettingRow icon={Type} label="Font size" description="Base text size">
            <Slider value={settings.fontSize} min={12} max={22} onChange={(v) => onUpdate({ fontSize: v })} label={`${settings.fontSize}px`} />
          </SettingRow>
        </div>
      </div>

      {/* Display */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wider mb-2">Display</h3>
        <div className="divide-y divide-white/5">
          <SettingRow icon={DollarSign} label="Currency" description="How values are shown">
            <select
              value={settings.currency}
              onChange={(e) => onUpdate({ currency: e.target.value as Settings["currency"] })}
              className="bg-slate-700/50 text-sm text-slate-200 rounded-lg px-3 py-1.5 border border-white/10 outline-none focus:border-indigo-500"
            >
              <option value="USD">USD only</option>
              <option value="SGD">SGD only</option>
              <option value="both">Both</option>
            </select>
          </SettingRow>

          <SettingRow icon={LayoutGrid} label="Compact cards" description="Smaller card layout">
            <Toggle on={settings.compactCards} onToggle={() => onUpdate({ compactCards: !settings.compactCards })} />
          </SettingRow>

          <SettingRow icon={ListChecks} label="Show decisions" description="Decision queue on portfolio">
            <Toggle on={settings.showDecisions} onToggle={() => onUpdate({ showDecisions: !settings.showDecisions })} />
          </SettingRow>

          <SettingRow icon={Home} label="Default tab" description="Tab shown on launch">
            <select
              value={settings.defaultTab}
              onChange={(e) => onUpdate({ defaultTab: Number(e.target.value) })}
              className="bg-slate-700/50 text-sm text-slate-200 rounded-lg px-3 py-1.5 border border-white/10 outline-none focus:border-indigo-500"
            >
              {TAB_NAMES.map((name, i) => (
                <option key={name} value={i}>{name}</option>
              ))}
            </select>
          </SettingRow>
        </div>
      </div>

      {/* Account */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-xs font-medium text-slate-300 uppercase tracking-wider mb-2">Account</h3>
        <button
          onClick={onLogout}
          className="flex items-center gap-3 w-full py-3 text-red-400 hover:text-red-300 transition-colors"
        >
          <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
            <LogOut size={16} />
          </div>
          <span className="text-sm font-medium">Lock app</span>
        </button>
      </div>

      <p className="text-center text-[10px] text-slate-600 mt-2">
        Casaa Finance v1.1
      </p>
    </div>
  );
}
