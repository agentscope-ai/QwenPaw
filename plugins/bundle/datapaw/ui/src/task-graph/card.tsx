import type { PlanSnapshot } from "./types";
import { TaskGraphPanel } from "./panel";
import { createPlanCorrectionPopover } from "./plan-correction-popover";
import { createTaskNodeDrawerBridge } from "./task-node-drawer-bridge";
import { resolveBackendSessionId } from "../lib/session-id";
import { refreshTaskCard } from "../patches/task-card";
import { putPlanSop } from "../lib/api";
import { tTaskGraph } from "./i18n";
import { getDisplayPlanById, subscribeCurrentPlan } from "../lib/plan-store";
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

export interface TaskGraphCardData {
  plan: PlanSnapshot;
  showActions?: boolean;
}

let lastCardRenderLogKey = "";

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  const label = `[DataPaw][TaskGraph][card] ${event}`;
  if (payload) console.debug(label, JSON.stringify(payload));
  else console.debug(label);
}

export function createTaskGraphCard(host: HostBundle) {
  const { React } = host;
  const { useEffect, useMemo, useState, useSyncExternalStore } = React;
  const PlanCorrectionPopover = createPlanCorrectionPopover(host);
  const TaskNodeDrawer = createTaskNodeDrawerBridge(host);

  return function TaskGraphCard({ data }: { data: TaskGraphCardData }) {
    const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);

    const initialPlan = data?.plan ? toPlainJson(data.plan) : null;
    const planFromStore = useSyncExternalStore(
      subscribeCurrentPlan,
      () => getDisplayPlanById(initialPlan?.id),
      () => initialPlan,
    );
    const plan = planFromStore ?? initialPlan;

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

    const cardRenderLogKey = [
      initialPlan?.id ?? "no-initial-plan",
      plan?.id ?? "no-plan",
      plan?.state ?? "no-state",
      sessionId || "no-session",
    ].join(":");
    if (cardRenderLogKey !== lastCardRenderLogKey) {
      lastCardRenderLogKey = cardRenderLogKey;
      logTaskGraphDebug("render", {
        hasInitialPlan: Boolean(initialPlan),
        initialPlanId: initialPlan?.id ?? null,
        hasPlan: Boolean(plan),
        planId: plan?.id ?? null,
        planState: plan?.state ?? null,
        nodeCount: plan ? Object.keys(plan.nodes ?? {}).length : 0,
        sessionId: sessionId || null,
        showActions: data.showActions ?? false,
      });
    }

    if (!plan) {
      logTaskGraphDebug("render-skip", {
        reason: "missing-plan",
        initialPlanId: initialPlan?.id ?? null,
      });
      return null;
    }

    const showActions = data.showActions ?? false;

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

    return React.createElement(
      React.Fragment,
      null,
      React.createElement(
        "div",
        { "data-datapaw-task-graph-card": true },
        React.createElement(TaskGraphPanel, {
          plan,
          React: host.React,
          antd: host.antd,
          PlanCorrectionPopover,
          showActions,
          onPlanCorrection: showActions ? handlePlanCorrection : undefined,
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
            showFollowTab: isNodeStreaming,
          })
        : null,
    );
  };
}
