import type { PlanSnapshot } from "./types";
import type { TaskGraphCardData } from "./TaskGraphCard";

export type TaskGraphCardMsgStatus = "generating" | "finished";

/** 运行时回调，由 TaskGraphActionsProvider 提供，不写入持久化消息 */
export interface TaskGraphCardActions {
  onNodeClick: (nodeId: string) => void;
  onPlanCorrection?: (yaml: string) => void;
  onMoreMenuClick?: (key: string) => void;
}

export function buildTaskGraphCardMessage(
  plan: PlanSnapshot,
  _actions?: TaskGraphCardActions,
  msgStatus: TaskGraphCardMsgStatus = "generating",
) {
  const data: TaskGraphCardData = {
    plan,
    showActions: true,
  };

  return {
    id: `task_graph_${plan.id}`,
    role: "assistant" as const,
    cards: [{ code: "task_graph" as const, data }],
    msgStatus,
  };
}
