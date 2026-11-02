/** Scoped durable clients. Callers choose intent IDs; retries never rotate them. */
import { hostFetch } from "../hostSdk/fetch";
import type { PawHostNamespace } from "./types";
import { assertContract } from "./contracts";
import type { ApprovalDecision, TaskAnswer, TaskHandle } from "./contracts";

export interface DurableOptions {
  workspaceId?: string;
  signal?: AbortSignal;
}
export interface DispatchOptions extends DurableOptions {
  requestId: string;
  appSessionId?: string;
}
export type DispatchResult =
  | { state: "accepted"; task: TaskHandle }
  | { state: "blocked"; reason: string; [key: string]: unknown };
const terminal = new Set(["succeeded", "failed", "cancelled", "interrupted"]);

function segment(value: string): string {
  if (!value || value.length > 256) throw new Error("invalid_identity");
  return encodeURIComponent(value);
}

export function createDurableNamespaces(
  appId: () => string,
  host: PawHostNamespace,
) {
  function scope(options: DurableOptions) {
    const workspaceId = options.workspaceId ?? host.getSelectedAgentId();
    return {
      workspaceId,
      prefix: `/pawapps/${segment(appId())}/workspaces/${segment(workspaceId)}`,
    };
  }
  async function call(
    path: string,
    options: DurableOptions = {},
    body?: unknown,
    method?: string,
  ) {
    const { prefix, workspaceId } = scope(options);
    const response = await hostFetch(prefix + path, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      signal: options.signal,
      headers: {
        "X-Agent-Id": workspaceId,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const payload = await response.json();
    if (!response.ok)
      throw new Error(
        typeof payload.detail === "string"
          ? payload.detail
          : `request_${response.status}`,
      );
    return payload;
  }
  function task(value: unknown, options: DurableOptions) {
    const parsed = assertContract("TaskHandle", value);
    if (
      parsed.scope.app_id !== appId() ||
      parsed.scope.workspace_id !== scope(options).workspaceId
    ) {
      throw new Error("task_scope_mismatch");
    }
    return parsed;
  }
  const tasks = {
    newRequestId: () =>
      globalThis.crypto?.randomUUID?.() ??
      Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join(""),
    async dispatch(
      actionId: string,
      inputs: Record<string, unknown>,
      options: DispatchOptions,
    ): Promise<DispatchResult> {
      options = { ...options, workspaceId: scope(options).workspaceId };
      segment(options.requestId);
      const result = await call(
        `/actions/${segment(actionId)}/direct-tasks`,
        options,
        {
          request_id: options.requestId,
          app_session_id: options.appSessionId ?? "default",
          inputs,
        },
      );
      if (result.state === "accepted")
        return { state: "accepted", task: task(result.task, options) };
      if (result.state === "blocked" && typeof result.reason === "string")
        return result;
      throw new Error("invalid_dispatch_result");
    },
    async get(taskId: string, options: DurableOptions = {}) {
      options = { ...options, workspaceId: scope(options).workspaceId };
      const result = task(
        (await call(`/tasks/${segment(taskId)}`, options)).task,
        options,
      );
      if (result.task_id !== taskId) throw new Error("task_identity_mismatch");
      return result;
    },
    async wait(
      taskId: string,
      options: DurableOptions = {},
    ): Promise<TaskHandle> {
      // Pin the workspace for the entire observation, even if the UI switches.
      const pinned = { ...options, workspaceId: scope(options).workspaceId };
      while (true) {
        pinned.signal?.throwIfAborted();
        const result = await tasks.get(taskId, pinned);
        if (
          terminal.has(result.status ?? "pending") ||
          result.status?.startsWith("waiting_")
        )
          return result;
        await new Promise<void>((resolve, reject) => {
          const abort = () => {
            clearTimeout(timer);
            reject(pinned.signal?.reason ?? new Error("aborted"));
          };
          const timer = setTimeout(() => {
            pinned.signal?.removeEventListener("abort", abort);
            resolve();
          }, 1000);
          pinned.signal?.addEventListener("abort", abort, { once: true });
        });
      }
    },
    async events(
      taskId: string,
      options: DurableOptions & { after?: number; limit?: number } = {},
    ) {
      const result = await call(
        `/tasks/${segment(taskId)}/events?after=${options.after ?? 0}&limit=${
          options.limit ?? 100
        }`,
        options,
      );
      if (!Array.isArray(result.events)) throw new Error("invalid_events");
      return result.events.map((event: unknown) => {
        const parsed = assertContract("TaskEvent", event);
        if (parsed.task_id !== taskId)
          throw new Error("event_identity_mismatch");
        return parsed;
      });
    },
    async answer(
      taskId: string,
      requestId: string,
      answers: TaskAnswer[],
      commandId: string,
      options: DurableOptions = {},
    ) {
      const result = await call(`/tasks/${segment(taskId)}/answer`, options, {
        command_id: commandId,
        request_id: requestId,
        answers,
      });
      const command = assertContract("TaskCommand", result.command);
      if (command.task_id !== taskId || command.command_id !== commandId)
        throw new Error("command_identity_mismatch");
      return command;
    },
    async decide(
      taskId: string,
      decision: ApprovalDecision,
      commandId: string,
      options: DurableOptions = {},
    ) {
      const result = await call(`/tasks/${segment(taskId)}/decide`, options, {
        command_id: commandId,
        decision: assertContract("ApprovalDecision", decision),
      });
      const command = assertContract("TaskCommand", result.command);
      if (
        command.task_id !== taskId ||
        command.command_id !== commandId ||
        command.kind !== "decide" ||
        command.request_id !== decision.request_id
      )
        throw new Error("command_identity_mismatch");
      return command;
    },
    async cancel(taskId: string, options: DurableOptions = {}) {
      const command = assertContract(
        "TaskCommand",
        (await call(`/tasks/${segment(taskId)}/cancel`, options, {})).command,
      );
      if (command.task_id !== taskId)
        throw new Error("command_identity_mismatch");
      return command;
    },
    async open(
      taskId: string,
      options: DurableOptions & {
        approval?: Pick<ApprovalDecision, "request_id" | "subject_digest">;
      } = {},
    ) {
      const action = assertContract(
        "OpenAppAction",
        (
          await call(
            `/tasks/${segment(taskId)}/open`,
            options,
            options.approval ?? {},
          )
        ).action,
      );
      if (
        action.app_id !== appId() ||
        action.project_ref.app_id !== appId() ||
        action.path !==
          `/apps/${appId()}?handoff=${encodeURIComponent(action.handoff_id)}`
      )
        throw new Error("invalid_open_action");
      return action;
    },
  };
  const artifacts = {
    async list(
      options: DurableOptions & {
        taskId?: string;
        mediaType?: string;
        limit?: number;
        cursor?: string;
      } = {},
    ) {
      const query = new URLSearchParams();
      if (options.taskId) query.set("task_id", options.taskId);
      if (options.mediaType) query.set("media_type", options.mediaType);
      if (options.limit) query.set("limit", String(options.limit));
      if (options.cursor) query.set("cursor", options.cursor);
      const result = assertContract(
        "ArtifactCollection",
        await call(`/artifacts?${query}`, options),
      );
      if (result.app_id !== appId()) throw new Error("artifact_scope_mismatch");
      return result;
    },
    async read(
      artifactId: string,
      version: number,
      options: DurableOptions = {},
    ) {
      if (!Number.isSafeInteger(version) || version < 1)
        throw new Error("invalid_artifact_version");
      const { prefix, workspaceId } = scope(options);
      const response = await hostFetch(
        `${prefix}/artifacts/${segment(
          artifactId,
        )}/versions/${version}/content?disposition=download`,
        { signal: options.signal, headers: { "X-Agent-Id": workspaceId } },
      );
      if (!response.ok) throw new Error(`artifact_${response.status}`);
      return response.blob();
    },
  };
  function setupRecord(
    value: unknown,
    options: DurableOptions,
    requestId?: string,
  ) {
    const result = value as {
      request: unknown;
      open_action?: unknown;
      result?: unknown;
    };
    const request = assertContract("SetupRequest", result.request);
    if (
      request.scope.app_id !== appId() ||
      request.scope.workspace_id !== scope(options).workspaceId ||
      (requestId !== undefined && request.request_id !== requestId)
    )
      throw new Error("setup_scope_mismatch");
    const open =
      result.open_action == null
        ? null
        : assertContract("SetupOpenAction", result.open_action);
    if (open) {
      const prefix = `/apps/${appId()}`;
      const path = open.path.split("?", 1)[0];
      if (
        open.app_id !== appId() ||
        open.request_id !== request.request_id ||
        (path !== prefix && !path.startsWith(prefix + "/")) ||
        /[\\#%]/.test(open.path) ||
        path.split("/").includes("..")
      )
        throw new Error("invalid_setup_navigation");
    }
    return {
      request,
      open_action: open,
      result:
        result.result == null
          ? null
          : assertContract("SetupResult", result.result),
    };
  }
  const setup = {
    async request(
      actionId: string,
      inputs: Record<string, unknown>,
      options: DispatchOptions & {
        entryId?: string;
        requirementIds?: string[];
      },
    ) {
      options = { ...options, workspaceId: scope(options).workspaceId };
      const result = await call(
        `/actions/${segment(actionId)}/direct-setup-requests`,
        options,
        {
          request_id: options.requestId,
          app_session_id: options.appSessionId ?? "default",
          inputs,
          entry_id: options.entryId,
          requirement_ids: options.requirementIds ?? [],
        },
      );
      return setupRecord(result, options);
    },
    async get(requestId: string, options: DurableOptions = {}) {
      options = { ...options, workspaceId: scope(options).workspaceId };
      const result = await call(
        `/setup-requests/${segment(requestId)}`,
        options,
      );
      return setupRecord(result, options, requestId);
    },
    async open(requestId: string, options: DurableOptions = {}) {
      options = { ...options, workspaceId: scope(options).workspaceId };
      const result = await call(
        `/setup-requests/${segment(requestId)}/open`,
        options,
        {},
      );
      return setupRecord(result, options, requestId);
    },
    async cancel(requestId: string, options: DurableOptions = {}) {
      options = { ...options, workspaceId: scope(options).workspaceId };
      const result = await call(
        `/setup-requests/${segment(requestId)}/cancel`,
        options,
        {},
      );
      return setupRecord(result, options, requestId);
    },
  };
  return { tasks, artifacts, setup };
}

export type PawTasksNamespace = ReturnType<
  typeof createDurableNamespaces
>["tasks"];
export type PawArtifactsNamespace = ReturnType<
  typeof createDurableNamespaces
>["artifacts"];
export type PawSetupNamespace = ReturnType<
  typeof createDurableNamespaces
>["setup"];
