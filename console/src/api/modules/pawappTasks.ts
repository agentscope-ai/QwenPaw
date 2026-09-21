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

export interface PawAppArtifactCollection {
  schema_version: 1;
  source: "host_artifacts";
  app_id: string;
  items: PawAppArtifactRef[];
  total_count: number;
  next_cursor: string | null;
}

export interface PawAppProjectRef {
  schema_version: 1;
  app_id: string;
  project_id: string;
  kind: string;
  revision: number;
}

export interface PawAppTaskInputOption {
  label: string;
  description: string;
}

export interface PawAppTaskInputQuestion {
  question: string;
  description: string;
  multi_select: boolean;
  options: PawAppTaskInputOption[];
}

export interface PawAppTaskInputRequest {
  request_id: string;
  title: string;
  questions: PawAppTaskInputQuestion[];
}

export interface PawAppTaskAnswer {
  question: string;
  selected_options: string[];
  custom_text: string | null;
}

export interface PawAppTaskCommand {
  protocol_version: 1;
  task_id: string;
  command_id: string;
  kind: "answer" | "cancel";
  request_id: string | null;
  state: "prepared" | "in_flight" | "accepted" | "rejected" | "unknown";
  reason: string | null;
}

export interface PawAppSetupOpenAction {
  schema_version: 1;
  app_id: string;
  request_id: string;
  entry_id: string;
  presentation: "chat_card" | "secure_form" | "app_entry";
  path: string;
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
  input_request?: PawAppTaskInputRequest | null;
  setup_request_id?: string | null;
  setup_attempt?: number;
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

export interface PawAppArtifactCollectionResult {
  kind: "pawapp_artifact_collection";
  app_id: string;
  workspace_id: string;
  collection: PawAppArtifactCollection;
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

function isArtifactRef(value: unknown): value is PawAppArtifactRef {
  return (
    record(value) &&
    value.schema_version === 1 &&
    identity(value.artifact_id) &&
    identity(value.type) &&
    Number.isSafeInteger(value.version) &&
    Number(value.version) >= 1 &&
    typeof value.name === "string" &&
    value.name.length > 0 &&
    value.name.length <= 512 &&
    typeof value.media_type === "string" &&
    value.media_type.length > 0 &&
    value.media_type.length <= 256 &&
    Number.isSafeInteger(value.size_bytes) &&
    Number(value.size_bytes) >= 0 &&
    typeof value.digest === "string" &&
    /^sha256:[0-9a-f]{64}$/.test(value.digest)
  );
}

function isArtifactCollection(
  value: unknown,
): value is PawAppArtifactCollection {
  return (
    record(value) &&
    value.schema_version === 1 &&
    value.source === "host_artifacts" &&
    typeof value.app_id === "string" &&
    /^[a-z0-9][a-z0-9-]*$/.test(value.app_id) &&
    Array.isArray(value.items) &&
    value.items.length <= 100 &&
        value.items.every(isArtifactRef) &&
    Number.isSafeInteger(value.total_count) &&
    Number(value.total_count) >= value.items.length &&
    (value.next_cursor === null ||
      (typeof value.next_cursor === "string" &&
        value.next_cursor.length > 0 &&
        value.next_cursor.length <= 512))
  );
}

function boundedString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length <= maxLength;
}

function isTaskInputRequest(value: unknown): value is PawAppTaskInputRequest {
  if (
    !record(value) ||
    !identity(value.request_id) ||
    !boundedString(value.title, 2000) ||
    !Array.isArray(value.questions) ||
    value.questions.length < 1 ||
    value.questions.length > 4
  )
    return false;
  return value.questions.every((question) => {
    if (
      !record(question) ||
      !boundedString(question.question, 2000) ||
      question.question.length === 0 ||
      !boundedString(question.description, 4000) ||
      typeof question.multi_select !== "boolean" ||
      !Array.isArray(question.options) ||
      question.options.length < 2 ||
      question.options.length > 4
    )
      return false;
    const labels = new Set<string>();
    return question.options.every((option) => {
      if (
        !record(option) ||
        !boundedString(option.label, 1000) ||
        option.label.length === 0 ||
        !boundedString(option.description, 2000) ||
        labels.has(option.label)
      )
        return false;
      labels.add(option.label);
      return true;
    });
  });
}

function isSetupOpenAction(
  value: unknown,
  appId: string,
  requestId: string,
): value is PawAppSetupOpenAction {
  if (
    !record(value) ||
    value.schema_version !== 1 ||
    value.app_id !== appId ||
    value.request_id !== requestId ||
    !identity(value.entry_id) ||
    !["chat_card", "secure_form", "app_entry"].includes(
      String(value.presentation),
    ) ||
    typeof value.path !== "string" ||
    value.path.length === 0 ||
    value.path.length > 2000 ||
    /[\\#%]/.test(value.path)
  )
    return false;
  const appPath = `/apps/${appId}`;
  const path = value.path.split("?", 1)[0];
  return (
    !path.split("/").includes("..") &&
    (path === appPath || path.startsWith(`${appPath}/`))
  );
}

function isTaskCommand(value: unknown): value is PawAppTaskCommand {
  return (
    record(value) &&
    value.protocol_version === 1 &&
    identity(value.task_id) &&
    identity(value.command_id) &&
    ["answer", "cancel"].includes(String(value.kind)) &&
    (value.request_id === null || identity(value.request_id)) &&
    ["prepared", "in_flight", "accepted", "rejected", "unknown"].includes(
      String(value.state),
    ) &&
    (value.reason === null || identity(value.reason))
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
        value.output_refs.every(isArtifactRef))) &&
    (value.project_ref === undefined ||
      value.project_ref === null ||
      isProjectRef(value.project_ref)) &&
    (value.input_request === undefined ||
      value.input_request === null ||
      isTaskInputRequest(value.input_request)) &&
    (value.setup_request_id === undefined ||
      value.setup_request_id === null ||
      identity(value.setup_request_id)) &&
    (value.setup_attempt === undefined ||
      (Number.isSafeInteger(value.setup_attempt) &&
        Number(value.setup_attempt) >= 0)) &&
    (value.setup_request_id === undefined ||
      value.setup_request_id === null ||
      (value.status === "waiting_for_setup" &&
        Number(value.setup_attempt) >= 1)) &&
    (value.input_request === undefined ||
      value.input_request === null ||
      ["waiting_for_input", "waiting_for_approval"].includes(
        String(value.status),
      ))
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

function decodeToolValue(value: unknown): unknown {
  for (let depth = 0; depth < 4; depth += 1) {
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
      continue;
    }
    if (typeof value === "string") {
      value = JSON.parse(value);
      continue;
    }
    return value;
  }
  return null;
}

export function parsePawAppTaskResult(value: unknown): PawAppTaskResult | null {
  try {
    value = decodeToolValue(value);
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

export function parsePawAppArtifactCollectionResult(
  value: unknown,
): PawAppArtifactCollectionResult | null {
  try {
    value = decodeToolValue(value);
    if (
      !record(value) ||
      value.kind !== "pawapp_artifact_collection" ||
      typeof value.app_id !== "string" ||
      !/^[a-z0-9][a-z0-9-]*$/.test(value.app_id) ||
      !identity(value.workspace_id) ||
      !isArtifactCollection(value.collection) ||
      value.collection.app_id !== value.app_id
    )
      return null;
    return value as unknown as PawAppArtifactCollectionResult;
  } catch {
    return null;
  }
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

export async function listPawAppArtifacts(
  appId: string,
  workspaceId: string,
  options: {
    cursor?: string;
    limit?: number;
    mediaType?: string;
    taskId?: string;
    signal?: AbortSignal;
  } = {},
): Promise<PawAppArtifactCollection> {
  const query = new URLSearchParams();
  if (options.cursor) query.set("cursor", options.cursor);
  if (options.limit !== undefined) query.set("limit", String(options.limit));
  if (options.mediaType) query.set("media_type", options.mediaType);
  if (options.taskId) query.set("task_id", options.taskId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const result = await request<unknown>(
    `/pawapps/${encodeURIComponent(appId)}/workspaces/${encodeURIComponent(
      workspaceId,
    )}/artifacts${suffix}`,
    { signal: options.signal, headers: { "X-Agent-Id": workspaceId } },
  );
  if (!isArtifactCollection(result) || result.app_id !== appId) {
    throw new Error("invalid_artifact_collection_response");
  }
  return result;
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

export async function openPawAppSetup(
  appId: string,
  workspaceId: string,
  requestId: string,
): Promise<PawAppSetupOpenAction> {
  const result = await request<{ open_action: unknown }>(
    `/pawapps/${encodeURIComponent(appId)}/workspaces/${encodeURIComponent(
      workspaceId,
    )}/setup-requests/${encodeURIComponent(requestId)}/open`,
    { method: "POST", headers: { "X-Agent-Id": workspaceId } },
  );
  if (!isSetupOpenAction(result.open_action, appId, requestId)) {
    throw new Error("invalid_open_setup_response");
  }
  return result.open_action;
}

export async function answerPawAppTask(
  appId: string,
  workspaceId: string,
  taskId: string,
  commandId: string,
  requestId: string,
  answers: PawAppTaskAnswer[],
): Promise<PawAppTaskCommand> {
  const result = await request<{ command: unknown }>(
    `/pawapps/${encodeURIComponent(appId)}/workspaces/${encodeURIComponent(
      workspaceId,
    )}/tasks/${encodeURIComponent(taskId)}/answer`,
    {
      method: "POST",
      headers: { "X-Agent-Id": workspaceId },
      body: JSON.stringify({
        command_id: commandId,
        request_id: requestId,
        answers,
      }),
    },
  );
  if (
    !isTaskCommand(result.command) ||
    result.command.task_id !== taskId ||
    result.command.command_id !== commandId ||
    result.command.kind !== "answer" ||
    result.command.request_id !== requestId
  ) {
    throw new Error("invalid_task_answer_response");
  }
  return result.command;
}
