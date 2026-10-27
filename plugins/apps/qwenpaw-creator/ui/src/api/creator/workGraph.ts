import type { WorkGraphView } from "@/contracts/creator/workGraph";

import { creatorRequest } from "./client";

function project(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

export function getWorkGraph(projectId: string): Promise<WorkGraphView> {
  return creatorRequest(`${project(projectId)}/work-graph`);
}

export function resumeWorkGraph(
  projectId: string,
  revision: number,
): Promise<{ ok: true }> {
  return creatorRequest(`${project(projectId)}/work-graph/resume`, {
    method: "POST",
    body: JSON.stringify({ revision }),
  });
}

export function dispatchWorkGraphNode(
  projectId: string,
  nodeId: string,
): Promise<{
  ok: boolean;
  nodeId: string;
  dispatched: boolean;
  status?: "running" | "done" | "dispatched";
}> {
  return creatorRequest(
    `${project(projectId)}/work-graph/nodes/${encodeURIComponent(
      nodeId,
    )}/dispatch`,
    { method: "POST" },
  );
}
