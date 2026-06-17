import type { PlanSnapshot } from "../task-graph/types";

export const TASK_GRAPH_MESSAGE_ID = "datapaw_task_graph";

const STORAGE_PREFIX = "datapaw_task_card:v1:";
const MAX_STORED_PLANS = 50;

export interface StoredTaskCardPlan {
  plan: PlanSnapshot;
  current?: boolean;
  updatedAt?: number;
}

function storageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
}

function sortStoredPlans(
  plans: StoredTaskCardPlan[],
): StoredTaskCardPlan[] {
  return [...plans].sort((a, b) => {
    const at = a.plan.created_at ? Date.parse(a.plan.created_at) : 0;
    const bt = b.plan.created_at ? Date.parse(b.plan.created_at) : 0;
    if (at !== bt) return at - bt;
    return (a.updatedAt ?? 0) - (b.updatedAt ?? 0);
  });
}

function parseStoredPlans(raw: string | null): StoredTaskCardPlan[] {
  if (!raw) return [];
  const parsed = JSON.parse(raw) as {
    plan?: PlanSnapshot;
    plans?: StoredTaskCardPlan[];
    updatedAt?: number;
  };
  if (Array.isArray(parsed.plans)) {
    return sortStoredPlans(
      parsed.plans.filter((item) => item?.plan?.id),
    );
  }
  if (parsed.plan?.id) {
    return [
      {
        plan: parsed.plan,
        current: true,
        updatedAt: parsed.updatedAt,
      },
    ];
  }
  return [];
}

function latestStoredPlan(plans: StoredTaskCardPlan[]): StoredTaskCardPlan | null {
  const current = plans.find((item) => item.current);
  return current ?? plans[plans.length - 1] ?? null;
}

export function buildTaskCardMessage(plan: PlanSnapshot) {
  return {
    id: TASK_GRAPH_MESSAGE_ID,
    role: "assistant" as const,
    cards: [
      {
        code: "task_graph" as const,
        data: { plan, showActions: true },
      },
    ],
    msgStatus: plan.state === "done" ? "finished" : "generating",
  };
}

export function saveTaskCardForSession(
  sessionId: string,
  plan: PlanSnapshot,
  opts: { current?: boolean } = { current: true },
): void {
  if (!sessionId) return;
  try {
    const existing = parseStoredPlans(localStorage.getItem(storageKey(sessionId)));
    const current = opts.current !== false;
    const updatedAt = Date.now();
    const nextById = new Map<string, StoredTaskCardPlan>();
    for (const item of existing) {
      nextById.set(item.plan.id, {
        ...item,
        current: current ? false : item.current,
      });
    }
    nextById.set(plan.id, { plan, current, updatedAt });
    const plans = sortStoredPlans([...nextById.values()]).slice(-MAX_STORED_PLANS);
    const latest = latestStoredPlan(plans);
    localStorage.setItem(
      storageKey(sessionId),
      JSON.stringify({
        version: 2,
        plan: latest?.plan ?? plan,
        plans,
        updatedAt,
      }),
    );
  } catch {
    /* quota / private mode */
  }
}

export function loadTaskCardPlans(sessionId: string): StoredTaskCardPlan[] {
  if (!sessionId) return [];
  try {
    return parseStoredPlans(localStorage.getItem(storageKey(sessionId)));
  } catch {
    return [];
  }
}

export function loadTaskCardPlan(sessionId: string): PlanSnapshot | null {
  if (!sessionId) return null;
  try {
    return (
      parseStoredPlans(localStorage.getItem(storageKey(sessionId))).find(
        (item) => item.current,
      )?.plan ?? null
    );
  } catch {
    return null;
  }
}

export function clearTaskCardCurrentForSession(sessionId: string): void {
  if (!sessionId) return;
  try {
    const existing = parseStoredPlans(localStorage.getItem(storageKey(sessionId)));
    if (!existing.length) return;
    const plans = sortStoredPlans(
      existing.map((item) => ({ ...item, current: false })),
    );
    const latest = latestStoredPlan(plans);
    localStorage.setItem(
      storageKey(sessionId),
      JSON.stringify({
        version: 2,
        plan: latest?.current ? latest.plan : null,
        plans,
        updatedAt: Date.now(),
      }),
    );
  } catch {
    /* quota / private mode */
  }
}

export function loadTaskCardMessage(
  sessionId: string,
): ReturnType<typeof buildTaskCardMessage> | null {
  void sessionId;
  return null;
}

export function removeTaskCardForSession(sessionId: string): void {
  if (!sessionId) return;
  try {
    localStorage.removeItem(storageKey(sessionId));
  } catch {
    /* ignore */
  }
}
