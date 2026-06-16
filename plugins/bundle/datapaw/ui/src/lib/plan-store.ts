import type { PlanSnapshot } from "../task-graph/types";
import { toPlainJson } from "./plain";
import { resolveBackendSessionId } from "./session-id";

type Listener = () => void;
export type StoredPlanSnapshot = PlanSnapshot & {
  __datapawCurrent?: boolean;
  __datapawSessionId?: string;
};

const plansBySession = new Map<string, Map<string, StoredPlanSnapshot>>();
const currentPlanIdBySession = new Map<string, string>();
const listeners = new Set<Listener>();
const EMPTY_STORED_PLANS: StoredPlanSnapshot[] = [];
let storeRevision = 0;
let cachedDisplayPlansSessionId: string | null = null;
let cachedDisplayPlansRevision = -1;
let cachedDisplayPlans: StoredPlanSnapshot[] = [];

function notifyPlanListeners(): void {
  storeRevision += 1;
  listeners.forEach((listener) => listener());
}

export function subscribeCurrentPlan(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function normalizeSessionId(sessionId?: string | null): string | null {
  return resolveBackendSessionId(sessionId);
}

export function getCurrentPlan(): PlanSnapshot | null {
  const sessionId = normalizeSessionId();
  if (!sessionId) return null;
  const currentPlanId = currentPlanIdBySession.get(sessionId);
  if (!currentPlanId) return null;
  return plansBySession.get(sessionId)?.get(currentPlanId) ?? null;
}

/** Prefer active plan; fall back to the newest known plan for the current session. */
export function getDisplayPlan(): PlanSnapshot | null {
  const plans = getDisplayPlans();
  const current = plans.find((plan) => plan.__datapawCurrent);
  return current ?? plans[plans.length - 1] ?? null;
}

export function getDisplayPlans(): StoredPlanSnapshot[] {
  const sessionId = normalizeSessionId();
  if (!sessionId) return EMPTY_STORED_PLANS;
  if (
    cachedDisplayPlansSessionId === sessionId &&
    cachedDisplayPlansRevision === storeRevision
  ) {
    return cachedDisplayPlans;
  }
  const plans = [...(plansBySession.get(sessionId)?.values() ?? [])];
  cachedDisplayPlans = plans.sort((a, b) => {
    const at = a.created_at ? Date.parse(a.created_at) : 0;
    const bt = b.created_at ? Date.parse(b.created_at) : 0;
    if (at !== bt) return at - bt;
    return a.id.localeCompare(b.id);
  });
  cachedDisplayPlansSessionId = sessionId;
  cachedDisplayPlansRevision = storeRevision;
  return cachedDisplayPlans;
}

export function getDisplayPlanById(planId?: string | null): StoredPlanSnapshot | null {
  if (!planId) return null;
  const sessionId = normalizeSessionId();
  if (!sessionId) return null;
  return plansBySession.get(sessionId)?.get(planId) ?? null;
}

export function clearStickyPlan(sessionId?: string | null): void {
  clearCurrentSessionPlans(sessionId);
}

export function clearCurrentSessionPlans(sessionId?: string | null): void {
  const normalizedSessionId = normalizeSessionId(sessionId);
  if (!normalizedSessionId) return;
  plansBySession.delete(normalizedSessionId);
  currentPlanIdBySession.delete(normalizedSessionId);
  notifyPlanListeners();
}

export function setCurrentPlan(
  plan: PlanSnapshot | null,
  sessionId?: string | null,
): void {
  const next = plan ? toPlainJson(plan) : null;
  const normalizedSessionId = normalizeSessionId(sessionId);
  if (!normalizedSessionId) return;
  if (!next) {
    const sessionPlans = plansBySession.get(normalizedSessionId);
    if (sessionPlans) {
      for (const [planId, storedPlan] of sessionPlans) {
        if (storedPlan.__datapawCurrent) {
          sessionPlans.set(planId, {
            ...storedPlan,
            __datapawCurrent: false,
          });
        }
      }
    }
    currentPlanIdBySession.delete(normalizedSessionId);
    notifyPlanListeners();
    return;
  }

  const sessionPlans =
    plansBySession.get(normalizedSessionId) ?? new Map<string, StoredPlanSnapshot>();
  const previousCurrentId = currentPlanIdBySession.get(normalizedSessionId);
  if (previousCurrentId && previousCurrentId !== next.id) {
    const previous = sessionPlans.get(previousCurrentId);
    if (previous) {
      sessionPlans.set(previousCurrentId, {
        ...previous,
        __datapawCurrent: false,
      });
    }
  }
  sessionPlans.set(next.id, {
    ...next,
    __datapawCurrent: true,
    __datapawSessionId: normalizedSessionId,
  });
  plansBySession.set(normalizedSessionId, sessionPlans);
  currentPlanIdBySession.set(normalizedSessionId, next.id);
  notifyPlanListeners();
}

export function upsertHistoricalPlan(
  plan: PlanSnapshot,
  sessionId?: string | null,
): void {
  const normalizedSessionId = normalizeSessionId(sessionId);
  if (!normalizedSessionId) return;
  const next = toPlainJson(plan);
  const sessionPlans =
    plansBySession.get(normalizedSessionId) ?? new Map<string, StoredPlanSnapshot>();
  const isCurrent = currentPlanIdBySession.get(normalizedSessionId) === next.id;
  sessionPlans.set(next.id, {
    ...next,
    __datapawCurrent: isCurrent,
    __datapawSessionId: normalizedSessionId,
  });
  plansBySession.set(normalizedSessionId, sessionPlans);
  notifyPlanListeners();
}
