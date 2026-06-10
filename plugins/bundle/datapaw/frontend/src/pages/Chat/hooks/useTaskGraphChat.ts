import { useCallback, useMemo, useRef, useState } from "react";
import type { TaskArtifact } from "../../../api/modules/tasks";
import type { PlanSnapshot } from "../components/TaskGraphPanel/types";
import type { TaskGraphActions } from "../components/TaskGraphPanel/TaskGraphActionsContext";
import { useTaskPanel } from "./useTaskPanel";
import {
  setCurrentPlan,
  getCurrentPlan,
} from "../../../../../ui/src/lib/plan-store";
import {
  saveTaskCardForSession,
  removeTaskCardForSession,
} from "../../../../../ui/src/lib/task-card-storage";

export interface UseTaskGraphChatOptions {
  sessionId: string | null;
  userId: string;
  enabled: boolean;
  onPlanReplaced?: () => void;
}

export function useTaskGraphChat({
  sessionId,
  userId,
  enabled,
  onPlanReplaced,
}: UseTaskGraphChatOptions) {
  const [currentPlan, setLocalPlan] = useState<PlanSnapshot | null>(
    () => getCurrentPlan(),
  );
  const [taskArtifacts, setTaskArtifacts] = useState<TaskArtifact[]>([]);
  const activePlanIdRef = useRef<string | null>(null);

  const handlePlanChange = useCallback(
    (plan: PlanSnapshot | null) => {
      const prevId = activePlanIdRef.current;

      if (!plan) {
        if (prevId && sessionId) {
          removeTaskCardForSession(sessionId);
        }
        activePlanIdRef.current = null;
        setLocalPlan(null);
        setCurrentPlan(null);
        setTaskArtifacts([]);
        return;
      }

      if (prevId && prevId !== plan.id) {
        onPlanReplaced?.();
      }

      activePlanIdRef.current = plan.id;
      setLocalPlan(plan);
      setCurrentPlan(plan);
      if (sessionId) {
        saveTaskCardForSession(sessionId, plan);
      }
    },
    [onPlanReplaced, sessionId],
  );

  const taskPanel = useTaskPanel({
    sessionId,
    userId,
    enabled,
    onPlanChange: handlePlanChange,
    onArtifactsChange: setTaskArtifacts,
  });

  const clearTaskGraph = useCallback(() => {
    if (sessionId) {
      removeTaskCardForSession(sessionId);
    }
    activePlanIdRef.current = null;
    setLocalPlan(null);
    setCurrentPlan(null);
    setTaskArtifacts([]);
  }, [sessionId]);

  const contextActions: TaskGraphActions = useMemo(
    () => ({
      onNodeClick: () => {},
      onPlanCorrection: () => {},
      onMoreMenuClick: () => {},
    }),
    [],
  );

  const getAllFiles = useMemo(() => {
    const fromNodes = currentPlan
      ? Object.values(currentPlan.nodes).flatMap((n) =>
          (n.output?.files || []).map((f) => ({
            ...f,
            _nodeName: n.name || n.node_id,
          })),
        )
      : [];
    const fromArtifacts = taskArtifacts.map((a) => ({
      name: a.name,
      path: a.path,
      mime_type: a.mime_type,
      size_bytes: a.size_bytes,
      preview_url: a.preview_url,
      download_url: a.download_url,
      _nodeName: currentPlan?.nodes[a.node_id]?.name || a.node_id,
    }));
    const seen = new Set<string>();
    return [...fromNodes, ...fromArtifacts].filter((file) => {
      if (seen.has(file.path)) return false;
      seen.add(file.path);
      return true;
    });
  }, [currentPlan, taskArtifacts]);

  return {
    currentPlan,
    taskArtifacts,
    taskPanel,
    contextActions,
    getAllFiles,
    clearTaskGraph,
  };
}
