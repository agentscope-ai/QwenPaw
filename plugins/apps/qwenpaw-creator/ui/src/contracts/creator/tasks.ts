import type { SpecialistRole } from "./common";

export type SpecialistRunStatus =
  | "QUEUED"
  | "QUEUED_CAPACITY"
  | "RUNNING_MODEL"
  | "WAITING_RUNTIME"
  | "WAITING_AUTHORIZATION"
  | "SUCCEEDED"
  | "BLOCKED"
  | "FAILED"
  | "STALE"
  | "CANCELLED";

export type TaskStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "QUARANTINED";

export interface SpecialistRunView {
  id: string;
  role: SpecialistRole;
  displayName: string;
  status: SpecialistRunStatus;
  targetRefs: string[];
  relatedRunId?: string;
  supersedesRunId?: string;
  finalMarker?: "SUCCESS" | "BLOCKED" | "FAILED";
  finalSummaryText?: string;
  taskRefs: string[];
  transactionId?: string | null;
  createdAt?: string;
  updatedAt?: string;
  metadata: Record<string, unknown>;
}

export interface TaskView {
  id: string;
  projectId: string;
  transactionId: string | null;
  specialistRunId: string | null;
  kind:
    | "asset_ingest"
    | "asset_import"
    | "source_intelligence"
    | "image_generation"
    | "r2v_generation"
    | "ai_edit_plan"
    | "ai_edit_execute"
    | "compose";
  targetRef: string;
  status: TaskStatus;
  progress: number | null;
  completedElements?: number | null;
  totalElements?: number | null;
  resultRefs: string[];
  result?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
  createdAt?: string;
  updatedAt?: string;
}

export interface TaskListResponse {
  items: TaskView[];
}

export interface SpecialistRunListResponse {
  items: SpecialistRunView[];
}

export interface ExecutionAuthorizationView {
  id: string;
  transactionId: string;
  specialistRunId: string;
  executionRequestId: string;
  targetRef: string;
  scope: Record<string, unknown>;
  status: "PENDING" | "APPROVED" | "DECLINED" | "EXPIRED";
  authorizationToken: string;
  provider: string;
  model: string;
  estimatedCost?: number;
  currency?: string;
  maxCandidates: number;
  createdAt: string;
}

export interface ExecutionAuthorizationDecision {
  authorizationToken: string;
}

export interface ExecutionAuthorizationApproval
  extends ExecutionAuthorizationDecision {
  provider: string;
  model: string;
  maxCost: number;
  maxCandidates: number;
}
