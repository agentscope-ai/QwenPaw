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
  manuallyHeld?: boolean;
  promptSyncRequired?: boolean;
  preparationState?: "waiting" | "running" | "failed" | null;
  /**
   * Why this artifact's automatic review was skipped instead of running —
   * currently only environment faults (a missing ffmpeg/ffprobe). The
   * backend drops the note once a newer version is selected or a review
   * round is admitted, so its presence is always about the current output.
   */
  reviewSkip?: { reason: string; hint: string } | null;
}

export interface WorkGraphView {
  projectId: string;
  generation: number;
  counts: Record<string, number>;
  mediaCalls: number;
  mediaCallBudget: number;
  manualHold?: { revision: number; nodeIds: string[] };
  nodes: WorkGraphNode[];
}
