/**
 * decisions/DecisionTabs.tsx — the navigation chrome for the Decisions page:
 * the Caspar/Sarah account tab bar, the All/Options/Stocks sub-tab bar, and the
 * small section header used above the Options / Stocks groups.
 *
 * Split verbatim out of the original monolithic ``DecisionsPage.tsx`` — behavior
 * and visual output are unchanged.
 */
import type { AccountTab, SubTab } from "./format";

export function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-1">
      <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">{count}</span>
    </div>
  );
}

export function AccountTabBar({ active, onChange, counts }: {
  active: AccountTab;
  onChange: (tab: AccountTab) => void;
  counts: { caspar: number; sarah: number };
}) {
  const tabs: { key: AccountTab; label: string }[] = [
    { key: "caspar", label: "Caspar" },
    { key: "sarah", label: "Sarah" },
  ];
  return (
    <div className="flex gap-1.5 p-1 rounded-xl bg-white/[0.03] border border-white/5">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[length:var(--t-xs)] font-semibold transition-all ${
            active === t.key
              ? "bg-white/[0.08] text-slate-100 shadow-sm"
              : "text-slate-500 hover:text-slate-400"
          }`}
        >
          {t.label}
          <span className={`tabular-nums text-[length:var(--t-2xs)] ${
            active === t.key ? "text-slate-400" : "text-slate-600"
          }`}>
            {counts[t.key]}
          </span>
        </button>
      ))}
    </div>
  );
}

export function SubTabBar({ active, onChange, counts }: {
  active: SubTab;
  onChange: (tab: SubTab) => void;
  counts: { all: number; options: number; stocks: number };
}) {
  const tabs: { key: SubTab; label: string }[] = [
    { key: "all", label: "All" },
    { key: "options", label: "Options" },
    { key: "stocks", label: "Stocks" },
  ];
  return (
    <div className="flex gap-1">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-[length:var(--t-2xs)] font-semibold transition-all ${
            active === t.key
              ? "bg-indigo-500/15 text-indigo-300 border border-indigo-500/25"
              : "bg-white/[0.03] text-slate-500 border border-white/5 hover:text-slate-400"
          }`}
        >
          {t.label}
          <span className="tabular-nums">{counts[t.key]}</span>
        </button>
      ))}
    </div>
  );
}
