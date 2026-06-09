import { createContext, useContext, type ReactNode } from "react";

export interface TaskGraphActions {
  onNodeClick: (nodeId: string) => void;
  onPlanCorrection?: (yaml: string) => void;
  onMoreMenuClick?: (key: string) => void;
}

const TaskGraphActionsContext = createContext<TaskGraphActions | null>(null);

export function TaskGraphActionsProvider({
  value,
  children,
}: {
  value: TaskGraphActions;
  children: ReactNode;
}) {
  return (
    <TaskGraphActionsContext.Provider value={value}>
      {children}
    </TaskGraphActionsContext.Provider>
  );
}

export function useTaskGraphActions(): TaskGraphActions | null {
  return useContext(TaskGraphActionsContext);
}
