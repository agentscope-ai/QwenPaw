import { request } from "../request";
import { getApiUrl } from "../config";

export const taskStatuses = [
  "pending",
  "running",
  "waiting_for_input",
  "waiting_for_setup",
  "waiting_for_approval",
  "paused",
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
] as const;
export type PawAppTaskStatus = (typeof taskStatuses)[number];

export interface PawAppArtifactRef {
  schema_version: 1;
  artifact_id: string;
  type: string;
  version: number;
  name: string;
  media_type: string;
  size_bytes: number;
  digest: string;
}

export interface PawAppProjectRef {
  schema_version: 1;
  app_id: string;
  project_id: string;
  kind: string;
  revision: number;
}

export interface PawAppTask {
  task_id: string;
  action_id: string;
  scope: { app_id: string; workspace_id: string; principal_id: string };
  status: PawAppTaskStatus;
  recovery_state: "none" | "reconciling" | "unresolved";
  event_sequence: number;
  text_result: string | null;
  output_refs?: PawAppArtifactRef[];
  project_ref?: PawAppProjectRef | null;
}

export interface PawAppOpenAction {
  schema_version: 1;
  app_id: string;
  handoff_id: string;
  path: string;
  project_ref: PawAppProjectRef;
}

export interface PawAppOpenResult {
  kind: "pawapp_open_app";
  app_id: string;
  workspace_id: string;
  action: PawAppOpenAction;
}

export interface PawAppTaskResult {
  kind: "pawapp_task";
  app_id: string;
  workspace_id: string;
  state: "accepted" | "blocked";
  task?: PawAppTask;
  reason?: string;
}

export function isTerminalTask(task: PawAppTask): boolean {
  return ["succeeded", "failed", "cancelled", "interrupted"].includes(
    task.status,
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function identity(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 256;
}

function isProjectRef(value: unknown): value is PawAppProjectRef {
  return (
    record(value) &&
    value.schema_version === 1 &&
    identity(value.app_id) &&
    /^[a-z0-9][a-z0-9-]*$/.test(value.app_id) &&
    identity(value.project_id) &&
    identity(value.kind) &&
    Number.isSafeInteger(value.revision) &&
    Number(value.revision) >= 1
  );
}

export function isPawAppTask(value: unknown): value is PawAppTask {
  if (!record(value) || !record(value.scope)) return false;
  return (
    identity(value.task_id) &&
    identity(value.action_id) &&
    identity(value.scope.app_id) &&
    identity(value.scope.workspace_id) &&
    identity(value.scope.principal_id) &&
    taskStatuses.includes(value.status as PawAppTaskStatus) &&
    ["none", "reconciling", "unresolved"].includes(
      String(value.recovery_state),
    ) &&
    Number.isSafeInteger(value.event_sequence) &&
    Number(value.event_sequence) >= 0 &&
    (value.text_result === null || typeof value.text_result === "string") &&
    (value.output_refs === undefined ||
      (Array.isArray(value.output_refs) &&
        value.output_refs.every(
          (ref) =>
            record(ref) &&
            ref.schema_version === 1 &&
            identity(ref.artifact_id) &&
            identity(ref.type) &&
            Number.isSafeInteger(ref.version) &&
            Number(ref.version) >= 1 &&
            typeof ref.name === "string" &&
            ref.name.length > 0 &&
            typeof ref.media_type === "string" &&
            ref.media_type.length > 0 &&
            Number.isSafeInteger(ref.size_bytes) &&
            Number(ref.size_bytes) >= 0 &&
            typeof ref.digest === "string" &&
            /^sha256:[0-9a-f]{64}$/.test(ref.digest),
        ))) &&
    (value.project_ref === undefined ||
      value.project_ref === null ||
      isProjectRef(value.project_ref))
  );
}

function isOpenAction(value: unknown): value is PawAppOpenAction {
  if (!record(value) || !isProjectRef(value.project_ref)) return false;
  if (
    value.schema_version !== 1 ||
    !identity(value.app_id) ||
    !/^[a-z0-9][a-z0-9-]*$/.test(value.app_id) ||
    !identity(value.handoff_id)
  )
    return false;
  return (
    value.project_ref.app_id === value.app_id &&
    value.path === `/apps/${value.app_id}?handoff=${value.handoff_id}`
  );
}

export function pawAppArtifactUrl(
  appId: string,
  workspaceId: string,
  artifactId: string,
  version: number,
  disposition: "preview" | "download" = "preview",
): string {
  const path = `/pawapps/${encodeURIComponent(
    appId,
  )}/workspaces/${encodeURIComponent(
    workspaceId,
  )}/artifacts/${encodeURIComponent(
    artifactId,
  )}/versions/${version}/content?disposition=${disposition}`;
  return getApiUrl(path);
}

export function parsePawAppTaskResult(value: unknown): PawAppTaskResult | null {
  try {
    // Both Chat renderers may supply text directly or as ToolChunk blocks.
    if (Array.isArray(value)) {
      if (
        !value.every(
          (block) =>
            record(block) &&
            block.type === "text" &&
            typeof block.text === "string",
        )
      )
        return null;
      value = value.map((block) => block.text).join("");
    }
    if (typeof value === "string") value = JSON.parse(value);
    if (
      !record(value) ||
      value.kind !== "pawapp_task" ||
      typeof value.app_id !== "string" ||
      !/^[a-z0-9][a-z0-9-]*$/.test(value.app_id) ||
      !identity(value.workspace_id)
    )
      return null;
    if (value.state === "blocked" && identity(value.reason)) {
      return {
        kind: "pawapp_task",
        state: "blocked",
        app_id: value.app_id,
        workspace_id: value.workspace_id,
        reason: value.reason,
      };
    }
    if (
      value.state !== "accepted" ||
      !isPawAppTask(value.task) ||
      value.task.scope.app_id !== value.app_id ||
      value.task.scope.workspace_id !== value.workspace_id
    )
      return null;
    return {
      kind: "pawapp_task",
      state: "accepted",
      app_id: value.app_id,
      workspace_id: value.workspace_id,
      task: value.task,
    };
  } catch {
    return null;
  }
}

function decodeToolValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    if (
      !value.every(
        (block) =>
          record(block) &&
          block.type === "text" &&
          typeof block.text === "string",
      )
    )
      return null;
    value = value.map((block) => block.text).join("");
  }
  return typeof value === "string" ? JSON.parse(value) : value;
}

export function parsePawAppOpenResult(value: unknown): PawAppOpenResult | null {
  try {
    value = decodeToolValue(value);
    if (
      !record(value) ||
      value.kind !== "pawapp_open_app" ||
      !identity(value.app_id) ||
      !/^[a-z0-9][a-z0-9-]*$/.test(value.app_id) ||
      !identity(value.workspace_id) ||
      !isOpenAction(value.action) ||
      value.action.app_id !== value.app_id
    )
      return null;
    return value as unknown as PawAppOpenResult;
  } catch {
    return null;
  }
}

export async function getPawAppTask(
  appId: string,
  workspaceId: string,
  taskId: string,
  signal: AbortSignal,
): Promise<PawAppTask> {
  const result = await request<{ task: unknown }>(
    `/pawapps/${encodeURIComponent(appId)}/workspaces/${encodeURIComponent(
      workspaceId,
    )}/tasks/${encodeURIComponent(taskId)}`,
    { signal, headers: { "X-Agent-Id": workspaceId } },
  );
  if (
    !isPawAppTask(result.task) ||
    result.task.task_id !== taskId ||
    result.task.scope.app_id !== appId ||
    result.task.scope.workspace_id !== workspaceId
  ) {
    throw new Error("invalid_task_response");
  }
  return result.task;
}

export async function openPawAppTask(
  appId: string,
  workspaceId: string,
  taskId: string,
): Promise<PawAppOpenAction> {
  const result = await request<{ action: unknown }>(
    `/pawapps/${encodeURIComponent(appId)}/workspaces/${encodeURIComponent(
      workspaceId,
    )}/tasks/${encodeURIComponent(taskId)}/open`,
    { method: "POST", headers: { "X-Agent-Id": workspaceId } },
  );
  if (
    !isOpenAction(result.action) ||
    result.action.app_id !== appId ||
    result.action.project_ref.app_id !== appId
  ) {
    throw new Error("invalid_open_app_response");
  }
  return result.action;
}
