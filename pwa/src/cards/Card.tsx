import type { ReactNode } from "react";

export function Card({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl bg-slate-800/60 border border-slate-700/50 p-4">
      {children}
    </div>
  );
}
