export type PlanToolStreamEvent = { name: string; phase: "call" | "result" };

/** Tools that should refresh the task card via GET /api/tasks. */
export const TASK_CARD_REFRESH_TOOLS = new Set(["create_plan", "finish_plan"]);
