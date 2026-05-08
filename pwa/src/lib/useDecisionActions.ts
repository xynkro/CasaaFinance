/**
 * React hook over the localStorage-backed decision-action journal.
 *
 * The lib functions in `./decisionActions` are pure read/write — this
 * hook layers on a useState so any component subscribing re-renders
 * when an action is recorded, undone, or read on mount. A single
 * source of truth (the localStorage value) keeps multiple consumers
 * (DecisionCard buttons, Review › Journal section) in sync without a
 * dedicated context provider.
 *
 * Storage events (cross-tab sync) are also wired so two open PWA tabs
 * stay in lockstep.
 */
import { useCallback, useEffect, useState } from "react";
import {
  type DecisionAction,
  getActions,
  setAction,
  clearAction,
} from "./decisionActions";

export function useDecisionActions() {
  const [actions, setActions] = useState<Map<string, DecisionAction>>(() => getActions());

  // Cross-tab sync: when localStorage changes in another tab, refresh.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === "casaa_decision_actions_v1") {
        setActions(getActions());
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const upsert = useCallback((a: DecisionAction) => {
    const next = setAction(a);
    setActions(new Map(next));
  }, []);

  const remove = useCallback((key: string) => {
    const next = clearAction(key);
    setActions(new Map(next));
  }, []);

  return { actions, upsert, remove };
}
