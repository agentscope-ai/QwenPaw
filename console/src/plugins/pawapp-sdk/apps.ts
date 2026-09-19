import { hostFetch } from "../hostSdk/fetch";
import type {
  PawAppsNamespace,
  PawArtifactRef,
  PawHandoffRequest,
  PawHostNamespace,
  PawProjectRef,
} from "./types";

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function identity(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 256;
}

function projectRef(value: unknown): value is PawProjectRef {
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

const producerFields = [
  "app_id",
  "action_id",
  "task_id",
  "executor_id",
  "session_id",
  "run_id",
  "source_id",
] as const;

function artifactProducer(value: unknown): value is Record<string, string> {
  return (
    record(value) && producerFields.every((field) => identity(value[field]))
  );
}

function artifactRef(value: unknown): value is PawArtifactRef {
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
    Number.isSafeInteger(value.size_bytes) &&
    Number(value.size_bytes) >= 0 &&
    typeof value.digest === "string" &&
    /^sha256:[0-9a-f]{64}$/.test(value.digest) &&
    artifactProducer(value.producer) &&
    Number.isFinite(value.created_at)
  );
}

function handoffRequest(
  value: unknown,
  appId: string,
  workspaceId: string,
  handoffId: string,
): value is PawHandoffRequest {
  if (
    !record(value) ||
    value.schema_version !== 1 ||
    value.handoff_id !== handoffId ||
    value.target_app_id !== appId ||
    !identity(value.source_app_id) ||
    !/^[a-z0-9][a-z0-9-]*$/.test(value.source_app_id) ||
    !Number.isFinite(value.created_at) ||
    !record(value.context)
  )
    return false;
  const context = value.context;
  return (
    context.schema_version === 1 &&
    identity(context.context_id) &&
    Number.isSafeInteger(context.revision) &&
    Number(context.revision) >= 1 &&
    identity(context.task_id) &&
    typeof context.goal === "string" &&
    context.goal.length <= 16000 &&
    record(context.scope) &&
    context.scope.workspace_id === workspaceId &&
    context.scope.source_app_id === value.source_app_id &&
    identity(context.scope.action_id) &&
    ["delegated", "direct"].includes(String(context.scope.engagement)) &&
    Array.isArray(context.artifact_refs) &&
    context.artifact_refs.length <= 128 &&
    context.artifact_refs.every(artifactRef) &&
    Array.isArray(context.decision_refs) &&
    context.decision_refs.length <= 128 &&
    context.decision_refs.every(artifactRef) &&
    projectRef(context.project_ref) &&
    identity(context.resume_ref)
  );
}

export function createAppsNamespace(
  appIdProvider: () => string,
  host: PawHostNamespace,
): PawAppsNamespace {
  return {
    async resolveHandoff(handoffId, options = {}) {
      if (!identity(handoffId)) throw new Error("invalid_handoff_id");
      const appId = appIdProvider();
      const workspaceId = options.workspaceId ?? host.getSelectedAgentId();
      if (!identity(workspaceId)) throw new Error("invalid_workspace_id");
      const response = await hostFetch(
        `/pawapps/${encodeURIComponent(appId)}/workspaces/${encodeURIComponent(
          workspaceId,
        )}/handoffs/${encodeURIComponent(handoffId)}`,
        { headers: { "X-Agent-Id": workspaceId } },
      );
      if (!response.ok) throw new Error(`handoff_${response.status}`);
      const payload = (await response.json()) as { handoff?: unknown };
      if (!handoffRequest(payload.handoff, appId, workspaceId, handoffId)) {
        throw new Error("invalid_handoff_response");
      }
      return payload.handoff;
    },
  };
}
