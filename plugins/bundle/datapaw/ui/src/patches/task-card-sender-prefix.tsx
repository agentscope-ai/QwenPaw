/**
 * Register the DataPaw task graph panel above the chat input via
 * `window.QwenPaw.chat.sender.addPrefix`. Plan state comes from plan-store
 * (updated by patches/task-card.ts on create_plan / DAG events).
 */
import { PLUGIN_ID } from "../lib/constants";
import { getSelectedAgentId, isDatapawAgentSelected } from "../lib/agent";
import {
  getDisplayPlan,
  getDisplayPlans,
  subscribeCurrentPlan,
} from "../lib/plan-store";
import { resolveBackendSessionId } from "../lib/session-id";
import { refreshTaskCard } from "./task-card";
import { TaskGraphPanel } from "../task-graph/panel";
import { createPlanCorrectionPopover } from "../task-graph/plan-correction-popover";
import { createTaskNodeDrawerBridge } from "../task-graph/task-node-drawer-bridge";
import { tTaskGraph } from "../task-graph/i18n";
import type { HostBundle } from "../types";
import {
  EMPTY_NODE_STREAM_EVENTS,
  getNodeStreamEvents,
  getNodeStreamRevision,
  snapshotCompletedNodeStreams,
  subscribeNodeStreamEvents,
} from "../lib/node-stream-events";
import { resolveDrawerStreamEvents } from "../lib/trace-to-stream";
import { toPlainJson } from "../lib/plain";
import { normalizeDrawerFile } from "@/pages/Chat/components/TaskGraphPanel/fileUtils";
import type { StreamEvent } from "@/pages/Chat/components/TaskGraphPanel/types";
import { putPlanSop } from "../lib/api";

const SENDER_PREFIX_ID = "datapaw-task-card-sender-prefix";
let lastGuardLogKey = "";

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  void event;
  void payload;
}

function useDatapawAgentSelected(React: HostBundle["React"]): boolean {
  const { useSyncExternalStore } = React;
  return useSyncExternalStore(
    (cb) => {
      const onStorage = () => cb();
      window.addEventListener("storage", onStorage);
      const timer = window.setInterval(cb, 800);
      return () => {
        window.removeEventListener("storage", onStorage);
        window.clearInterval(timer);
      };
    },
    isDatapawAgentSelected,
    () => false,
  );
}

export function createTaskCardSenderPrefix(host: HostBundle) {
  const { React } = host;
  const { useEffect, useMemo, useState, useSyncExternalStore } = React;
  const PlanCorrectionPopover = createPlanCorrectionPopover(host);
  const TaskNodeDrawer = createTaskNodeDrawerBridge(host);

  return function TaskCardSenderPrefix() {
    const datapawAgent = useDatapawAgentSelected(React);
    const plan = useSyncExternalStore(
      subscribeCurrentPlan,
      getDisplayPlan,
      () => null,
    );
    const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);

    const streamRevision = useSyncExternalStore(
      subscribeNodeStreamEvents,
      getNodeStreamRevision,
      () => 0,
    );

    const liveStreamEvents = drawerNodeId
      ? getNodeStreamEvents(drawerNodeId)
      : EMPTY_NODE_STREAM_EVENTS;

    const sessionId = resolveBackendSessionId() || "";
    const userId =
      (window as Window & { currentUserId?: string }).currentUserId ||
      "default";

    const selectedAgentId = getSelectedAgentId();
    const displayPlans = getDisplayPlans();
    const guardLogKey = [
      datapawAgent ? "datapaw" : selectedAgentId || "no-agent",
      plan?.id ?? "no-plan",
      sessionId || "no-session",
      displayPlans.length,
    ].join(":");
    if (guardLogKey !== lastGuardLogKey) {
      lastGuardLogKey = guardLogKey;
      logTaskGraphDebug("render-guard", {
        datapawAgent,
        selectedAgentId,
        hasPlan: Boolean(plan),
        planId: plan?.id ?? null,
        planState: plan?.state ?? null,
        displayPlanCount: displayPlans.length,
        displayPlans: displayPlans.map((item) => ({
          id: item.id,
          state: item.state,
          current: Boolean(item.__datapawCurrent),
          anchorMessageId: item.anchor_message_id ?? null,
        })),
        sessionId: sessionId || null,
        userId,
      });
    }

    const drawerNode =
      drawerNodeId && plan
        ? toPlainJson(plan.nodes[drawerNodeId] ?? null)
        : null;

    const isNodeStreaming = drawerNode?.state === "in_progress";

    useEffect(() => {
      if (plan?.nodes) {
        snapshotCompletedNodeStreams(plan.nodes);
      }
    }, [plan]);

    const streamEvents = useMemo(() => {
      if (!drawerNode) return [] as StreamEvent[];
      return resolveDrawerStreamEvents(
        drawerNode,
        liveStreamEvents,
        isNodeStreaming,
      );
    }, [drawerNode, liveStreamEvents, streamRevision, isNodeStreaming]);

    const allFiles = useMemo(() => {
      if (!plan) return [];
      const seen = new Set<string>();
      const items = [];
      for (const node of Object.values(plan.nodes)) {
        const nodeName = node.name || node.node_id;
        for (const file of node.output?.files || []) {
          const normalized = normalizeDrawerFile(file, nodeName);
          if (!normalized) continue;
          const key = normalized.path || normalized.name;
          if (seen.has(key)) continue;
          seen.add(key);
          items.push(normalized);
        }
      }
      return items;
    }, [plan]);

    const handlePlanCorrection = async (yaml: string) => {
      if (!sessionId) {
        host.antd.message?.error?.(tTaskGraph("noSession"));
        return;
      }
      try {
        const result = await putPlanSop(sessionId, yaml);
        await refreshTaskCard(sessionId);
        host.antd.message?.success?.(
          result.detail || tTaskGraph("planUpdateSuccess"),
        );
      } catch (error) {
        const msg =
          error instanceof Error
            ? error.message
            : tTaskGraph("planUpdateFailed");
        host.antd.message?.error?.(msg || tTaskGraph("planUpdateFailed"));
      }
    };

    if (!datapawAgent || !plan) return null;

    return React.createElement(
      "div",
      {
        className: "datapaw-task-card-sender-prefix",
        "data-datapaw-task-card-sender-prefix": true,
      },
      React.createElement(
        "div",
        { "data-datapaw-task-graph-card": true },
        React.createElement(TaskGraphPanel, {
          plan,
          React: host.React,
          antd: host.antd,
          PlanCorrectionPopover,
          showActions: true,
          onPlanCorrection: handlePlanCorrection,
          onNodeClick: (nodeId: string) => setDrawerNodeId(nodeId),
        }),
      ),
      drawerNode
        ? React.createElement(TaskNodeDrawer, {
            node: drawerNode,
            allFiles,
            isStreaming: isNodeStreaming,
            streamEvents,
            sessionId,
            userId,
            onClose: () => setDrawerNodeId(null),
            showFollowTab: isNodeStreaming || drawerNode?.state === "done" || drawerNode?.state === "failed",
          })
        : null,
    );
  };
}

export function registerTaskCardSenderPrefix(host: HostBundle): void {
  const chat = (
    window as {
      QwenPaw?: {
        chat?: {
          sender?: {
            addPrefix: (
              pluginId: string,
              node: unknown,
              opts?: { id?: string; order?: number },
            ) => { dispose: () => void };
          };
        };
      };
    }
  ).QwenPaw?.chat;

  if (!chat?.sender?.addPrefix) {
    logTaskGraphDebug("register-skip", {
      reason: "missing-chat-sender-addPrefix",
      hasChat: Boolean(chat),
      hasSender: Boolean(chat?.sender),
    });
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.chat.sender.addPrefix missing — task card dock skipped`,
    );
    return;
  }

  const Prefix = createTaskCardSenderPrefix(host);
  logTaskGraphDebug("register", { id: SENDER_PREFIX_ID });
  chat.sender.addPrefix(PLUGIN_ID, host.React.createElement(Prefix), {
    id: SENDER_PREFIX_ID,
    order: 0,
  });
}
