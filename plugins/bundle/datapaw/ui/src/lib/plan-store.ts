import type { PlanSnapshot } from "../task-graph/types";
import { toPlainJson } from "./plain";

type Listener = () => void;

let currentPlan: PlanSnapshot | null = null;
const listeners = new Set<Listener>();

export function subscribeCurrentPlan(listener: Listener): () => void {
  listeners.add(listener);
  console.info("[datapaw:plan-store] subscribed", {
    listenerCount: listeners.size,
  });
  return () => listeners.delete(listener);
}

export function getCurrentPlan(): PlanSnapshot | null {
  return currentPlan;
}

export function setCurrentPlan(plan: PlanSnapshot | null): void {
  const next = plan ? toPlainJson(plan) : null;
  if (currentPlan === next) return;
  currentPlan = next;
  console.info("[datapaw:plan-store] setCurrentPlan", {
    hasPlan: Boolean(next),
    planId: next?.id,
    planName: next?.name,
    listenerCount: listeners.size,
  });
  listeners.forEach((listener) => listener());
}
