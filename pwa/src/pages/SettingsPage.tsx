import type { Settings } from "../settings";
import { LogOut, DollarSign, LayoutGrid, ListChecks, Home } from "lucide-react";

const TAB_NAMES = ["Home", "Caspar", "Sarah", "Decisions", "Settings"];

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
          <div className="text-sm font-medium text-slate-200">{label}</div>
          {description && <div className="text-xs text-slate-500">{description}</div>}
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
      {/* Display */}
      <div className="glass rounded-2xl p-5">
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Display</h3>
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
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Account</h3>
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
        Casaa Finance v1.0
      </p>
    </div>
  );
}
