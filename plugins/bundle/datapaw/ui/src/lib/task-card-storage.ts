import type { PlanSnapshot } from "../task-graph/types";

export const TASK_GRAPH_MESSAGE_ID = "datapaw_task_graph";

const STORAGE_PREFIX = "datapaw_task_card:v1:";

function storageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
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
): void {
  if (!sessionId) return;
  try {
    localStorage.setItem(
      storageKey(sessionId),
      JSON.stringify({ plan, updatedAt: Date.now() }),
    );
  } catch {
    /* quota / private mode */
  }
}

export function loadTaskCardPlan(sessionId: string): PlanSnapshot | null {
  if (!sessionId) return null;
  try {
    const raw = localStorage.getItem(storageKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { plan?: PlanSnapshot };
    return parsed?.plan ?? null;
  } catch {
    return null;
  }
}

export function loadTaskCardMessage(
  sessionId: string,
): ReturnType<typeof buildTaskCardMessage> | null {
  const plan = loadTaskCardPlan(sessionId);
  if (!plan) return null;
  return buildTaskCardMessage(plan);
}

export function removeTaskCardForSession(sessionId: string): void {
  if (!sessionId) return;
  try {
    localStorage.removeItem(storageKey(sessionId));
  } catch {
    /* ignore */
  }
}
