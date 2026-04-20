import { Home, Briefcase, CircleDot, Target, Archive, Settings } from "lucide-react";

const TABS = [
  { icon: Home,       label: "Home",      color: "indigo" },
  { icon: Briefcase,  label: "Portfolio", color: "emerald" },
  { icon: CircleDot,  label: "Options",   color: "amber" },
  { icon: Target,     label: "Decisions", color: "cyan" },
  { icon: Archive,    label: "Archive",   color: "pink" },
  { icon: Settings,   label: "Settings",  color: "slate" },
] as const;

const COLOR_MAP: Record<string, string> = {
  indigo:  "text-indigo-400",
  emerald: "text-emerald-400",
  amber:   "text-amber-400",
  cyan:    "text-cyan-400",
  pink:    "text-pink-400",
  slate:   "text-slate-300",
};

export function TabBar({
  active,
  onChange,
  decisionCount,
  defenseAlerts,
}: {
  active: number;
  onChange: (i: number) => void;
  decisionCount?: number;
  defenseAlerts?: number;
}) {
  return (
    <nav className="tabbar-base">
      <div className="flex relative">
        {TABS.map((tab, i) => {
          const Icon = tab.icon;
          const isActive = active === i;
          const activeColor = COLOR_MAP[tab.color];
          const showDecision = tab.label === "Decisions" && decisionCount && decisionCount > 0;
          const showDefense = tab.label === "Options" && defenseAlerts && defenseAlerts > 0;

          return (
            <button
              key={tab.label}
              onClick={() => onChange(i)}
              className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 relative transition-all ${
                isActive ? activeColor : "text-slate-500 active:text-slate-300"
              }`}
            >
              <div className="relative">
                <Icon size={19} strokeWidth={isActive ? 2.4 : 1.75} />
                {isActive && (
                  <div className={`absolute -inset-2.5 rounded-full bg-${tab.color}-500/12 -z-10 pulse-glow`} />
                )}
                {showDecision && (
                  <div className="absolute -top-1.5 -right-2.5 min-w-[17px] h-[17px] px-1 rounded-full bg-amber-500 flex items-center justify-center shadow-lg shadow-amber-500/40">
                    <span className="text-[9px] font-bold text-black">{decisionCount}</span>
                  </div>
                )}
                {showDefense && (
                  <div className="absolute -top-1.5 -right-2.5 min-w-[17px] h-[17px] px-1 rounded-full bg-red-500 flex items-center justify-center shadow-lg shadow-red-500/40">
                    <span className="text-[9px] font-bold text-white">{defenseAlerts}</span>
                  </div>
                )}
              </div>
              <span className={`text-[9px] font-semibold ${isActive ? activeColor : ""}`}>
                {tab.label}
              </span>
              {isActive && (
                <div
                  className={`absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full`}
                  style={{ background: `rgb(var(--accent-rgb))` }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
