import React from 'react';
import type { PlanSnapshot } from './types';
import TaskGraphPanel from './index';
import { useTaskGraphActions } from './TaskGraphActionsContext';

export interface TaskGraphCardData {
  plan: PlanSnapshot;
  showActions?: boolean;
}

/**
 * 任务卡片 — 注册为 chat cards.task_graph
 * 计划数据来自消息 data.plan；交互回调由 TaskGraphActionsProvider 注入
 */
const TaskGraphCard: React.FC<{ data: TaskGraphCardData }> = ({ data }) => {
  const actions = useTaskGraphActions();
  if (!data?.plan) return null;

  return (
    <TaskGraphPanel
      plan={data.plan}
      onNodeClick={actions?.onNodeClick ?? (() => {})}
      onPlanCorrection={actions?.onPlanCorrection}
      onMoreMenuClick={actions?.onMoreMenuClick}
      showActions={data.showActions ?? true}
    />
  );
};

export default TaskGraphCard;
