/** Plan / graph tools in chat SSE that should refresh GET /api/tasks for the task card. */
export const TASK_CARD_REFRESH_TOOLS = new Set([
  "create_plan",
  "finish_plan",
  "revise_current_plan",
]);

export type PlanToolStreamEvent = { name: string; phase: "call" | "result" };

export function isTaskCardRefreshTool(name: string | undefined): boolean {
  return Boolean(name && TASK_CARD_REFRESH_TOOLS.has(name));
}
