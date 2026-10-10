export type WorkNodeStatus =
  | "done"
  | "running"
  | "waiting_review"
  | "failed"
  | "gated"
  | "ready"
  | "stale";

export interface WorkGraphNode {
  id: string;
  kind: "script" | "visual" | "lineup" | "storyboard" | "video" | "compose";
  label: string;
  status: WorkNodeStatus;
  deps: string[];
  lane: string;
  taskId: string | null;
  timelineId?: string | null;
  progress: number | null;
  error: string | null;
  missing: string[];
  locator: Record<string, string>;
  dispatchable: boolean;
  promptSyncRequired?: boolean;
  preparationState?: "waiting" | "running" | "failed" | null;
}

export interface WorkGraphView {
  projectId: string;
  generation: number;
  counts: Record<string, number>;
  mediaCalls: number;
  mediaCallBudget: number;
  nodes: WorkGraphNode[];
}
