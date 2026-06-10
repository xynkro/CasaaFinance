import { useState } from "react";
import { Card } from "./Card";
import { HelpCircle, ChevronDown, ChevronUp } from "lucide-react";

const LS_KEY = "casaa_scanner_howto_collapsed";

/**
 * Collapsible "how to use this page" explainer for the Scanner (IV surface)
 * page. Defaults OPEN until the user collapses it once; the choice persists.
 */
export function ScannerHowTo() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(LS_KEY) === "1";
    } catch {
      return false;
    }
  });

  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(LS_KEY, c ? "0" : "1");
      } catch {
        // ignore
      }
      return !c;
    });
  };

  return (
    <Card>
      <button
        onClick={toggle}
        className="w-full flex items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30 rounded"
        aria-expanded={!collapsed}
      >
        <HelpCircle size={14} className="text-sky-400 shrink-0" />
        <span className="text-[length:var(--t-xs)] font-semibold text-slate-300 uppercase tracking-wide flex-1">
          How to use this page
        </span>
        {collapsed ? (
          <ChevronDown size={14} className="text-slate-500" />
        ) : (
          <ChevronUp size={14} className="text-slate-500" />
        )}
      </button>

      {!collapsed && (
        <div className="mt-2 space-y-2">
          <p className="text-[length:var(--t-xs)] text-slate-400 leading-relaxed">
            This page finds <span className="text-slate-200 font-semibold">expensive options to SELL</span>.
            Each trading day (10:38 ET) it fits a fair-value volatility curve per ticker from live
            quotes — any contract whose actual IV sits <em>above</em> that curve is trading rich:
            you collect more premium than its neighbours for the same risk.
          </p>
          <ul className="space-y-1.5 text-[length:var(--t-2xs)] text-slate-400 leading-relaxed">
            <li>
              <span className="text-slate-300 font-semibold">Chart</span> — each dot is a contract;
              the dashed line is fitted "fair" IV. Dots far <em>above</em> the line = rich premium.
            </li>
            <li>
              <span className="text-slate-300 font-semibold">+pp</span> — how many vol points above
              fair (iv_excess). <span className="text-slate-300 font-semibold">Dl</span> — delta ≈
              odds of assignment.
            </li>
            <li>
              <span className="text-slate-300 font-semibold">Top Candidates</span> — the richest
              <em> sellable</em> contracts across every scanned ticker (real bid ≥ $0.10, |Δ| 0.05–0.45,
              plus your assignment-risk filter). Tap one to jump to its chain.
            </li>
            <li>
              <span className="text-slate-300 font-semibold">A good wheel sell</span> — +pp ≥ +3,
              |Δ| 0.15–0.35, DTE 15–50, tight bid/ask, and no warning dots
              (<span className="text-red-400">red</span> = earnings before expiry,{" "}
              <span className="text-amber-400">amber</span> = thin liquidity).
            </li>
            <li>
              Rich premium is rich for a reason as often as not — treat this as a{" "}
              <em>shortlist generator</em>, then check the name against the Options page gates
              before selling anything.
            </li>
          </ul>
        </div>
      )}
    </Card>
  );
}
