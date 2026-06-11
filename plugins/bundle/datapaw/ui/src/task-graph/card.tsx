import type { PlanSnapshot } from "./types";
import { TaskGraphPanel } from "./panel";
import { createArtifactManageDrawerBridge } from "./artifact-manage-drawer-bridge";
import { createTaskNodeDrawerBridge } from "./task-node-drawer-bridge";
import { resolveBackendSessionId } from "../lib/session-id";
import { getCurrentPlan, subscribeCurrentPlan } from "../lib/plan-store";
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

export interface TaskGraphCardData {
  plan: PlanSnapshot;
  showActions?: boolean;
}

export function createTaskGraphCard(host: HostBundle) {
  const { React } = host;
  const { useMemo, useState, useSyncExternalStore } = React;
  const ArtifactManageDrawer = createArtifactManageDrawerBridge(host);
  const TaskNodeDrawer = createTaskNodeDrawerBridge(host);

  return function TaskGraphCard({ data }: { data: TaskGraphCardData }) {
    const [artifactOpen, setArtifactOpen] = useState(false);
    const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);

    const initialPlan = data?.plan ? toPlainJson(data.plan) : null;
    const planFromStore = useSyncExternalStore(
      subscribeCurrentPlan,
      getCurrentPlan,
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

    if (!plan) return null;

    const showActions = data.showActions ?? false;

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
          showActions,
          onArtifactManage: showActions ? () => setArtifactOpen(true) : undefined,
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
