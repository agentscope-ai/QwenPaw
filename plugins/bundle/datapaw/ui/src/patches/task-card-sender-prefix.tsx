/**
 * Register the DataPaw task graph panel above the chat input via
 * `window.QwenPaw.chat.sender.addPrefix`. Plan state comes from plan-store
 * (updated by patches/task-card.ts on create_plan / DAG events).
 */
import { PLUGIN_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";
import { getCurrentPlan, subscribeCurrentPlan } from "../lib/plan-store";
import { resolveBackendSessionId } from "../lib/session-id";
import { refreshTaskCard } from "./task-card";
import { TaskGraphPanel } from "../task-graph/panel";
import { createPlanCorrectionPopover } from "../task-graph/plan-correction-popover";
import { createArtifactManageDrawerBridge } from "../task-graph/artifact-manage-drawer-bridge";
import { createTaskNodeDrawerBridge } from "../task-graph/task-node-drawer-bridge";
import { tTaskGraph } from "../task-graph/i18n";
import type { HostBundle } from "../types";
import {
  EMPTY_NODE_STREAM_EVENTS,
  getNodeStreamEvents,
  getNodeStreamRevision,
  subscribeNodeStreamEvents,
} from "../lib/node-stream-events";
import {
  mergeStreamEvents,
  traceToStreamEvents,
} from "../lib/trace-to-stream";
import { toPlainJson } from "../lib/plain";
import { normalizeDrawerFile } from "@/pages/Chat/components/TaskGraphPanel/fileUtils";
import type { StreamEvent } from "@/pages/Chat/components/TaskGraphPanel/types";
import { putPlanSop } from "../lib/api";

const SENDER_PREFIX_ID = "datapaw-task-card-sender-prefix";

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
  const { useMemo, useState, useSyncExternalStore } = React;
  const PlanCorrectionPopover = createPlanCorrectionPopover(host);
  const ArtifactManageDrawer = createArtifactManageDrawerBridge(host);
  const TaskNodeDrawer = createTaskNodeDrawerBridge(host);

  return function TaskCardSenderPrefix() {
    const datapawAgent = useDatapawAgentSelected(React);
    const plan = useSyncExternalStore(
      subscribeCurrentPlan,
      getCurrentPlan,
      () => null,
    );
    const [artifactOpen, setArtifactOpen] = useState(false);
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

    const drawerNode =
      drawerNodeId && plan
        ? toPlainJson(plan.nodes[drawerNodeId] ?? null)
        : null;

    const isNodeStreaming = drawerNode?.state === "in_progress";

    const streamEvents = useMemo(() => {
      if (!drawerNode) return [] as StreamEvent[];
      const persisted = traceToStreamEvents(drawerNode);
      return mergeStreamEvents(persisted, liveStreamEvents, isNodeStreaming);
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
          onArtifactManage: () => setArtifactOpen(true),
          onNodeClick: (nodeId: string) => setDrawerNodeId(nodeId),
        }),
      ),
      React.createElement(ArtifactManageDrawer, {
        open: artifactOpen,
        onClose: () => setArtifactOpen(false),
        sessionId,
        userId,
        graphId: plan.id,
      }),
      drawerNode
        ? React.createElement(TaskNodeDrawer, {
            node: drawerNode,
            allFiles,
            isStreaming: isNodeStreaming,
            streamEvents,
            sessionId,
            userId,
            onClose: () => setDrawerNodeId(null),
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
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.chat.sender.addPrefix missing — task card dock skipped`,
    );
    return;
  }

  const Prefix = createTaskCardSenderPrefix(host);
  chat.sender.addPrefix(PLUGIN_ID, host.React.createElement(Prefix), {
    id: SENDER_PREFIX_ID,
    order: 0,
  });

  console.info(
    `[${PLUGIN_ID}] Task card registered above chat input (sender.addPrefix)`,
  );
}
