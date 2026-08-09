import type {
  ExecutionAuthorizationApproval,
  ExecutionAuthorizationDecision,
  ExecutionAuthorizationView,
  SpecialistRole,
  SpecialistRunListResponse,
  SpecialistRunView,
  SpecialistRunStatus,
  TaskListResponse,
  TaskView,
} from "@/contracts/creator";
import { creatorRequest, jsonBody, newClientId } from "./client";
import i18n from "@/i18n";

const project = (id: string) => `/projects/${encodeURIComponent(id)}`;

export function listSpecialistRuns(
  projectId: string,
  filters: { status?: SpecialistRunStatus; role?: SpecialistRole } = {},
): Promise<SpecialistRunListResponse> {
  const query = new URLSearchParams();
  if (filters.status) query.set("status", filters.status);
  if (filters.role) query.set("role", filters.role);
  const suffix = query.size ? `?${query}` : "";
  return creatorRequest(`${project(projectId)}/specialist-runs${suffix}`);
}

export function getSpecialistRun(
  projectId: string,
  runId: string,
): Promise<SpecialistRunView> {
  return creatorRequest(
    `${project(projectId)}/specialist-runs/${encodeURIComponent(runId)}`,
  );
}

export function listTasks(projectId: string): Promise<TaskListResponse> {
  return creatorRequest(`${project(projectId)}/tasks`);
}

export function getTask(projectId: string, taskId: string): Promise<TaskView> {
  return creatorRequest(
    `${project(projectId)}/tasks/${encodeURIComponent(taskId)}`,
  );
}

export function cancelTask(
  projectId: string,
  taskId: string,
): Promise<TaskView> {
  const id = newClientId("cancel-task");
  return creatorRequest(
    `${project(projectId)}/tasks/${encodeURIComponent(taskId)}/cancel`,
    {
      method: "POST",
      headers: { "Idempotency-Key": id },
      body: jsonBody({ reason: i18n.t("api.userCancel") }),
    },
  );
}

export interface TimelineRenderResult {
  ok: boolean;
  taskId: string;
  artifactVersionId: string | null;
  generation: number;
  etag: string;
  replayed: boolean;
}

/** User-initiated final-cut export: deterministic compositing, no Agent. */
export function renderTimeline(
  projectId: string,
  timelineId: string,
  clientRequestId = newClientId("timeline-render"),
): Promise<TimelineRenderResult> {
  return creatorRequest(
    `${project(projectId)}/timelines/${encodeURIComponent(timelineId)}/render`,
    {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId },
    },
  );
}

export function listFileExecutionAuthorizations(
  projectId: string,
  status = "PENDING",
): Promise<{ items: ExecutionAuthorizationView[] }> {
  return creatorRequest(
    `${project(projectId)}/execution-authorizations?status=${encodeURIComponent(
      status,
    )}`,
  );
}

export function approveFileExecutionAuthorization(
  projectId: string,
  authorizationId: string,
  request: ExecutionAuthorizationApproval,
  clientRequestId = newClientId("authorization-approve"),
): Promise<ExecutionAuthorizationView> {
  return creatorRequest(
    `${project(projectId)}/execution-authorizations/${encodeURIComponent(
      authorizationId,
    )}/approve`,
    {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId },
      body: jsonBody(request),
    },
  );
}

export function declineFileExecutionAuthorization(
  projectId: string,
  authorizationId: string,
  request: ExecutionAuthorizationDecision,
  clientRequestId = newClientId("authorization-decline"),
): Promise<ExecutionAuthorizationView> {
  return creatorRequest(
    `${project(projectId)}/execution-authorizations/${encodeURIComponent(
      authorizationId,
    )}/decline`,
    {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId },
      body: jsonBody(request),
    },
  );
}
