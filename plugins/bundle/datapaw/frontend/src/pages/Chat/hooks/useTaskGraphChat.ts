import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";
import type { TaskArtifact } from "../../../api/modules/tasks";
import {
  buildTaskGraphCardMessage,
  type TaskGraphCardActions,
} from "../components/TaskGraphPanel/buildTaskGraphCard";
import type { PlanSnapshot } from "../components/TaskGraphPanel/types";
import type { TaskGraphActions } from "../components/TaskGraphPanel/TaskGraphActionsContext";
import sessionApi from "../sessionApi";
import { useTaskPanel } from "./useTaskPanel";

export interface UseTaskGraphChatOptions {
  chatRef: RefObject<IAgentScopeRuntimeWebUIRef | null>;
  sessionId: string | null;
  userId: string;
  enabled: boolean;
  onPlanReplaced?: () => void;
}

export function useTaskGraphChat({
  chatRef,
  sessionId,
  userId,
  enabled,
  onPlanReplaced,
}: UseTaskGraphChatOptions) {
  const [currentPlan, setCurrentPlan] = useState<PlanSnapshot | null>(null);
  const [taskArtifacts, setTaskArtifacts] = useState<TaskArtifact[]>([]);
  const activePlanIdRef = useRef<string | null>(null);

  const safeRemoveMessageById = useCallback((msgId: string) => {
    try {
      chatRef.current?.messages?.removeMessage?.({ id: msgId } as { id: string });
    } catch (e) {
      console.warn("[TaskGraph] removeMessage failed:", msgId, e);
    }
  }, [chatRef]);

  const removeTaskCard = useCallback(
    (planId: string) => {
      const msgId = `task_graph_${planId}`;
      sessionApi.removePersistentMessage(msgId);
      safeRemoveMessageById(msgId);
      chatRef.current?.messages?.updateMessage?.({
        id: msgId,
        role: "assistant",
        cards: [],
        msgStatus: "finished",
      });
    },
    [chatRef, safeRemoveMessageById],
  );

  const upsertTaskCard = useCallback(
    (plan: PlanSnapshot, actions: TaskGraphCardActions) => {
      const msgStatus = plan.state === "done" ? "finished" : "generating";
      const cardMsg = buildTaskGraphCardMessage(plan, actions, msgStatus);
      sessionApi.setPersistentMessage(cardMsg);
      safeRemoveMessageById(cardMsg.id);
      chatRef.current?.messages?.updateMessage?.(cardMsg);
    },
    [chatRef, safeRemoveMessageById],
  );

  const handlePlanChange = useCallback(
    (plan: PlanSnapshot | null) => {
      const prevId = activePlanIdRef.current;

      if (!plan) {
        if (prevId) {
          removeTaskCard(prevId);
          activePlanIdRef.current = null;
        }
        setCurrentPlan(null);
        setTaskArtifacts([]);
        return;
      }

      if (prevId && prevId !== plan.id) {
        removeTaskCard(prevId);
        onPlanReplaced?.();
      }

      activePlanIdRef.current = plan.id;
      setCurrentPlan(plan);
    },
    [onPlanReplaced, removeTaskCard],
  );

  const taskPanel = useTaskPanel({
    sessionId,
    userId,
    enabled,
    onPlanChange: handlePlanChange,
    onArtifactsChange: setTaskArtifacts,
  });

  const taskGraphActionsRef = useRef<TaskGraphCardActions>({
    onNodeClick: () => {},
  });

  const syncCardToChat = useCallback(() => {
    if (!currentPlan) return;
    upsertTaskCard(currentPlan, taskGraphActionsRef.current);
  }, [currentPlan, upsertTaskCard]);

  useEffect(() => {
    syncCardToChat();
  }, [syncCardToChat]);

  const clearTaskGraph = useCallback(() => {
    if (activePlanIdRef.current) {
      removeTaskCard(activePlanIdRef.current);
      activePlanIdRef.current = null;
    }
    setCurrentPlan(null);
    setTaskArtifacts([]);
  }, [removeTaskCard]);

  const contextActions: TaskGraphActions = useMemo(
    () => ({
      onNodeClick: (nodeId) => taskGraphActionsRef.current.onNodeClick(nodeId),
      onPlanCorrection: (yaml) => taskGraphActionsRef.current.onPlanCorrection?.(yaml),
      onMoreMenuClick: (key) => taskGraphActionsRef.current.onMoreMenuClick?.(key),
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
    taskGraphActionsRef,
    contextActions,
    getAllFiles,
    clearTaskGraph,
    syncCardToChat,
  };
}
