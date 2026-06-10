export type PlanToolStreamEvent = { name: string; phase: "call" | "result" };

/** Chat SSE tool name that gates the first GET /api/tasks for task cards. */
export const TASK_CARD_STREAM_TOOL = "create_plan";
