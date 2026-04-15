import { Home, User, Users, Settings } from "lucide-react";

const TABS = [
  { icon: Home, label: "Home" },
  { icon: User, label: "Caspar" },
  { icon: Users, label: "Sarah" },
  { icon: Settings, label: "Settings" },
] as const;

export function TabBar({ active, onChange }: { active: number; onChange: (i: number) => void }) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 pb-safe-bottom">
      <div className="mx-auto max-w-lg glass-bright border-t border-white/5 backdrop-blur-xl">
        <div className="flex">
          {TABS.map((tab, i) => {
            const Icon = tab.icon;
            const isActive = active === i;
            return (
              <button
                key={tab.label}
                onClick={() => onChange(i)}
                className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 pt-3 transition-all ${
                  isActive
                    ? "text-indigo-400"
                    : "text-slate-500 active:text-slate-300"
                }`}
              >
                <div className="relative">
                  <Icon size={20} strokeWidth={isActive ? 2.2 : 1.8} />
                  {isActive && (
                    <div className="absolute -inset-2 rounded-full bg-indigo-500/10 -z-10" />
                  )}
                </div>
                <span className={`text-[10px] font-medium ${isActive ? "text-indigo-400" : ""}`}>
                  {tab.label}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
