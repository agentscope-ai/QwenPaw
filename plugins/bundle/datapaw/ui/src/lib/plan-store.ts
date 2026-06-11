import type { PlanSnapshot } from "../task-graph/types";
import { toPlainJson } from "./plain";

type Listener = () => void;

let currentPlan: PlanSnapshot | null = null;
/** Last known plan kept after finish_plan clears current_plan on the backend. */
let stickyPlan: PlanSnapshot | null = null;
const listeners = new Set<Listener>();

function notifyPlanListeners(): void {
  listeners.forEach((listener) => listener());
}

export function subscribeCurrentPlan(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getCurrentPlan(): PlanSnapshot | null {
  return currentPlan;
}

/** Prefer active plan; fall back to sticky plan after graph is archived. */
export function getDisplayPlan(): PlanSnapshot | null {
  return currentPlan ?? stickyPlan;
}

export function clearStickyPlan(): void {
  if (!stickyPlan) return;
  stickyPlan = null;
  notifyPlanListeners();
}

export function setCurrentPlan(plan: PlanSnapshot | null): void {
  const next = plan ? toPlainJson(plan) : null;
  if (next) {
    stickyPlan = next;
  }
  if (currentPlan === next) return;
  currentPlan = next;
  console.info("[datapaw:plan-store] setCurrentPlan", {
    hasPlan: Boolean(next),
    hasSticky: Boolean(stickyPlan),
    planId: next?.id ?? stickyPlan?.id,
    planName: next?.name ?? stickyPlan?.name,
    listenerCount: listeners.size,
  });
  notifyPlanListeners();
}
