/**
 * Inline action recorder for a single DecisionCard.
 *
 * Renders one of three states:
 *   1. No action recorded → buttons: [Mark Filled] [Killed] [Defer]
 *   2. "Filled" form expanded → fill price + qty inputs + Confirm/Cancel
 *   3. Action recorded → status badge with running P&L (filled only) + Undo
 *
 * Compact by design — fits inside the existing DecisionCard footer
 * without needing a separate modal. The state is sourced from the
 * useDecisionActions() hook so multiple cards stay in sync.
 */
import { useState } from "react";
import type { DecisionRow } from "../data";
import {
  type DecisionAction,
  type DecisionActionType,
  fillPnl,
  keyForDecision,
  markDeferred,
  markFilled,
  markKilled,
} from "../lib/decisionActions";
import { useDecisionActions } from "../lib/useDecisionActions";
import { CheckCircle, XCircle, Clock4, Undo2, Pencil } from "lucide-react";

const SHORT_STRATS = ["BUY_DIP", "TRIM"];

function daysSince(iso: string): number {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}

export function DecisionActionRow({
  decision,
  currentPrice,
}: {
  decision: DecisionRow;
  currentPrice?: number;
}) {
  const { actions, upsert, remove } = useDecisionActions();
  const key = keyForDecision(decision);
  const existing = actions.get(key);

  if (existing) {
    return <RecordedBadge action={existing} currentPrice={currentPrice} onUndo={() => remove(key)} />;
  }
  return <Picker decision={decision} onPicked={(a) => upsert(a)} />;
}

/* ----------------------------- Picker ------------------------------ */

function Picker({
  decision,
  onPicked,
}: {
  decision: DecisionRow;
  onPicked: (a: DecisionAction) => void;
}) {
  const [mode, setMode] = useState<DecisionActionType | null>(null);
  const [fillPrice, setFillPrice] = useState<string>(decision.entry || "");
  const [qty, setQty] = useState<string>(decision.qty || "");

  if (mode === "filled") {
    const isShare = SHORT_STRATS.includes(decision.strategy ?? "");
    const qtyLabel = isShare ? "Shares" : "Contracts";
    return (
      <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-white/5">
        <span className="text-[length:var(--t-2xs)] uppercase tracking-wider text-emerald-400/80 font-semibold">
          Mark Filled
        </span>
        <NumberField label="Fill $" value={fillPrice} onChange={setFillPrice} placeholder="731.56" />
        <NumberField label={qtyLabel} value={qty} onChange={setQty} placeholder="10" />
        <button
          type="button"
          className="px-3 py-1.5 rounded-lg text-[length:var(--t-2xs)] font-semibold bg-emerald-500/15 border border-emerald-500/25 text-emerald-300 active:scale-95 transition"
          onClick={(e) => {
            e.stopPropagation();
            const fp = Number(fillPrice);
            const q = Number(qty);
            if (!fp || fp <= 0 || !q || q <= 0) return;
            onPicked(buildFilled(decision, fp, q));
            setMode(null);
          }}
        >
          Confirm
        </button>
        <button
          type="button"
          className="px-3 py-1.5 rounded-lg text-[length:var(--t-2xs)] text-slate-400 active:scale-95 transition"
          onClick={(e) => { e.stopPropagation(); setMode(null); }}
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-3 pt-3 border-t border-white/5">
      <span className="text-[length:var(--t-2xs)] uppercase tracking-wider text-slate-500 font-semibold mr-1">
        Action
      </span>
      <ActionButton
        label="Filled"
        Icon={CheckCircle}
        accent="#34d399"
        onClick={() => setMode("filled")}
      />
      <ActionButton
        label="Killed"
        Icon={XCircle}
        accent="#fca5a5"
        onClick={() => onPicked(buildKilled(decision))}
      />
      <ActionButton
        label="Defer"
        Icon={Clock4}
        accent="#fcd34d"
        onClick={() => onPicked(buildDeferred(decision))}
      />
    </div>
  );
}

function ActionButton({
  label,
  Icon,
  accent,
  onClick,
}: {
  label: string;
  Icon: typeof CheckCircle;
  accent: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[length:var(--t-2xs)] font-medium active:scale-95 transition"
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid rgba(255,255,255,0.07)",
        color: accent,
      }}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
    >
      <Icon size={11} />
      {label}
    </button>
  );
}

function NumberField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[length:var(--t-2xs)] text-slate-400">
      <span>{label}</span>
      <input
        type="number"
        inputMode="decimal"
        step="any"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        className="w-20 px-2 py-1 rounded-md bg-white/5 border border-white/10 text-white tabular-nums text-[length:var(--t-2xs)] focus:outline-none focus:border-emerald-400/40"
      />
    </label>
  );
}

/* ---------------------------- Recorded ----------------------------- */

function RecordedBadge({
  action,
  currentPrice,
  onUndo,
}: {
  action: DecisionAction;
  currentPrice?: number;
  onUndo: () => void;
}) {
  const cfg = ACTION_CONFIG[action.action];
  const Icon = cfg.icon;
  const days = daysSince(action.recordedAt);

  let pnlText: { text: string; color: string } | null = null;
  if (action.action === "filled") {
    const pnl = fillPnl(action, currentPrice);
    if (pnl) {
      const sign = pnl.pct >= 0 ? "+" : "";
      pnlText = {
        text: `${sign}${pnl.pct.toFixed(1)}% · ${sign}$${Math.abs(pnl.absUsd).toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
        color: pnl.pct >= 0 ? "#34d399" : "#fca5a5",
      };
    }
  }

  return (
    <div
      className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-3 pt-3 border-t border-white/5 text-[length:var(--t-2xs)]"
      style={{ color: cfg.color }}
    >
      <Icon size={12} />
      <span className="font-semibold">{cfg.label}</span>
      {action.action === "filled" && action.fillPrice && (
        <>
          <span className="text-slate-700">·</span>
          <span className="text-slate-300 tabular-nums">${action.fillPrice.toFixed(2)}</span>
        </>
      )}
      {action.action === "filled" && action.qty && (
        <>
          <span className="text-slate-700">·</span>
          <span className="text-slate-300 tabular-nums">{action.qty} {SHORT_STRATS.includes(action.strategy) ? "sh" : "ct"}</span>
        </>
      )}
      <span className="text-slate-700">·</span>
      <span className="text-slate-500">{days === 0 ? "today" : `${days}d ago`}</span>
      {pnlText && (
        <>
          <span className="text-slate-700">·</span>
          <span className="font-semibold tabular-nums" style={{ color: pnlText.color }}>
            {pnlText.text}
          </span>
        </>
      )}
      <button
        type="button"
        className="ml-auto flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 active:scale-95 transition"
        onClick={(e) => { e.stopPropagation(); onUndo(); }}
        aria-label="Undo action"
      >
        <Undo2 size={11} />
        <span>Undo</span>
      </button>
    </div>
  );
}

const ACTION_CONFIG: Record<
  DecisionActionType,
  { label: string; color: string; icon: typeof CheckCircle }
> = {
  filled:   { label: "Filled",   color: "#34d399", icon: CheckCircle },
  killed:   { label: "Killed",   color: "#fca5a5", icon: XCircle },
  deferred: { label: "Deferred", color: "#fcd34d", icon: Clock4 },
};

/* --------------------------- Action builders ----------------------- */

function buildFilled(d: DecisionRow, fp: number, q: number): DecisionAction {
  return {
    decisionKey: keyForDecision(d),
    ticker: (d.ticker || "").toUpperCase(),
    account: (d.account || "").toLowerCase(),
    strategy: (d.strategy || "").toUpperCase(),
    decisionDate: (d.date || "").slice(0, 10),
    action: "filled",
    fillPrice: fp,
    qty: q,
    recordedAt: new Date().toISOString(),
  };
}
function buildKilled(d: DecisionRow): DecisionAction {
  return {
    decisionKey: keyForDecision(d),
    ticker: (d.ticker || "").toUpperCase(),
    account: (d.account || "").toLowerCase(),
    strategy: (d.strategy || "").toUpperCase(),
    decisionDate: (d.date || "").slice(0, 10),
    action: "killed",
    recordedAt: new Date().toISOString(),
  };
}
function buildDeferred(d: DecisionRow): DecisionAction {
  return {
    decisionKey: keyForDecision(d),
    ticker: (d.ticker || "").toUpperCase(),
    account: (d.account || "").toLowerCase(),
    strategy: (d.strategy || "").toUpperCase(),
    decisionDate: (d.date || "").slice(0, 10),
    action: "deferred",
    recordedAt: new Date().toISOString(),
  };
}

// Suppress unused-warning for the lib helpers — kept exported for callers
// outside this component (e.g. brain-emitted import path or tests).
void [markFilled, markKilled, markDeferred, Pencil];
