import type { WorkGraphView } from "@/contracts/creator/workGraph";

import { creatorRequest } from "./client";

function project(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

export function getWorkGraph(projectId: string): Promise<WorkGraphView> {
  return creatorRequest(`${project(projectId)}/work-graph`);
}

export function dispatchWorkGraphNode(
  projectId: string,
  nodeId: string,
): Promise<{ ok: boolean; nodeId: string; dispatched: boolean }> {
  return creatorRequest(
    `${project(projectId)}/work-graph/nodes/${encodeURIComponent(
      nodeId,
    )}/dispatch`,
    { method: "POST" },
  );
}
