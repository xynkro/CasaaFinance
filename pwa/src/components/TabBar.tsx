import { Home, User, Users, Target, BarChart3, Archive, Settings } from "lucide-react";

const TABS = [
  { icon: Home, label: "Home" },
  { icon: User, label: "Caspar" },
  { icon: Users, label: "Sarah" },
  { icon: Target, label: "Decisions" },
  { icon: BarChart3, label: "History" },
  { icon: Archive, label: "Archive" },
  { icon: Settings, label: "Settings" },
] as const;

export function TabBar({
  active,
  onChange,
  decisionCount,
}: {
  active: number;
  onChange: (i: number) => void;
  decisionCount?: number;
}) {
  return (
    <nav className="relative z-30 shrink-0 pb-safe-bottom glass-bright border-t border-white/5">
      <div className="flex">
        {TABS.map((tab, i) => {
          const Icon = tab.icon;
          const isActive = active === i;
          const showBadge = tab.label === "Decisions" && decisionCount && decisionCount > 0;
          return (
            <button
              key={tab.label}
              onClick={() => onChange(i)}
              className={`flex-1 flex flex-col items-center gap-0.5 py-2 pt-2.5 transition-all ${
                isActive
                  ? "text-indigo-400"
                  : "text-slate-500 active:text-slate-300"
              }`}
            >
              <div className="relative">
                <Icon size={17} strokeWidth={isActive ? 2.2 : 1.8} />
                {isActive && (
                  <div className="absolute -inset-2 rounded-full bg-indigo-500/10 -z-10" />
                )}
                {showBadge && (
                  <div className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-full bg-amber-500 flex items-center justify-center">
                    <span className="text-[9px] font-bold text-black">{decisionCount}</span>
                  </div>
                )}
              </div>
              <span className={`text-[8px] font-medium ${isActive ? "text-indigo-400" : ""}`}>
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
