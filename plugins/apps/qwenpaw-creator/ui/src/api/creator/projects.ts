import type {
  ProjectCreateRequest,
  ProjectCreateResponse,
  ProjectListResponse,
  ProjectPatchRequest,
  ProjectPatchResponse,
  ProjectServerSyncStatus,
  ProjectSnapshotEnvelope,
  ProjectSnapshotPollResult,
} from "@/contracts/creator";
import {
  CreatorHttpError,
  creatorFetch,
  creatorRequest,
  jsonBody,
  newClientId,
} from "./client";

function syncStatus(
  value: unknown,
  fallback: ProjectServerSyncStatus,
): ProjectServerSyncStatus {
  return value === "healthy" || value === "degraded" || value === "invalid"
    ? value
    : fallback;
}

function optionalGeneration(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

async function responseObject(
  response: Response,
): Promise<Record<string, unknown>> {
  try {
    const value = (await response.json()) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/**
 * Read the canonical Project snapshot.  304 is a successful protocol result,
 * not an HTTP error, so it is intentionally handled outside creatorRequest.
 */
export async function getProjectSnapshot(
  projectId: string,
  etag?: string | null,
): Promise<ProjectSnapshotPollResult> {
  const headers = new Headers();
  if (etag) headers.set("If-None-Match", etag);
  const response = await creatorFetch(
    `/projects/${encodeURIComponent(projectId)}/project`,
    { headers },
    { timeoutMs: 30_000 },
  );
  const responseEtag = response.headers?.get("ETag") ?? null;
  const responseGeneration = optionalGeneration(
    response.headers?.get("X-Project-Generation"),
  );
  const responseSyncStatus = syncStatus(
    response.headers?.get("X-Project-Sync-Status"),
    "healthy",
  );

  if (response.status === 304) {
    return {
      kind: "not_modified",
      etag: responseEtag ?? etag ?? null,
      generation: responseGeneration,
      syncStatus: responseSyncStatus,
    };
  }

  const body = await responseObject(response);
  if (!response.ok) {
    if (body.code === "PROJECT_INVALID") {
      return {
        kind: "invalid",
        code: "PROJECT_INVALID",
        syncStatus: "invalid",
        lastGoodGeneration: optionalGeneration(
          body.lastGoodGeneration ?? body.last_good_generation,
        ),
        message:
          typeof body.message === "string"
            ? body.message
            : "project.json 未通过校验",
      };
    }
    throw new CreatorHttpError(response.status, {
      code: typeof body.code === "string" ? body.code : undefined,
      message:
        typeof body.message === "string" ? body.message : response.statusText,
      retryable:
        typeof body.retryable === "boolean" ? body.retryable : undefined,
      details:
        body.details &&
        typeof body.details === "object" &&
        !Array.isArray(body.details)
          ? (body.details as Record<string, unknown>)
          : undefined,
    });
  }

  const generation = optionalGeneration(body.generation);
  const bodyProjectId = body.projectId ?? body.project_id;
  const project = body.project;
  const resultEtag =
    responseEtag ?? (typeof body.etag === "string" ? body.etag : null);
  if (
    bodyProjectId !== projectId ||
    generation === null ||
    !resultEtag ||
    !project ||
    typeof project !== "object" ||
    Array.isArray(project)
  ) {
    throw new Error("Project snapshot response is malformed");
  }
  const documentProjectId = (project as Record<string, unknown>).project_id;
  if (
    typeof documentProjectId === "string" &&
    documentProjectId !== projectId
  ) {
    throw new Error(
      `Project snapshot mismatch: expected ${projectId}, received ${documentProjectId}`,
    );
  }

  return {
    kind: "updated",
    projectId,
    generation,
    etag: resultEtag,
    syncStatus: syncStatus(
      body.syncStatus ?? body.sync_status,
      responseSyncStatus,
    ),
    project: project as ProjectSnapshotEnvelope["project"],
  };
}

export function listProjects(
  limit = 100,
  offset = 0,
  sortBy: "updated_at" | "created_at" | "name" = "updated_at",
  sortOrder: "asc" | "desc" = "desc",
): Promise<ProjectListResponse> {
  return creatorRequest(
    `/projects?limit=${limit}&offset=${offset}&sort_by=${sortBy}&sort_order=${sortOrder}`,
  );
}

export function createProject(
  request: ProjectCreateRequest,
): Promise<ProjectCreateResponse> {
  return creatorRequest("/projects", {
    method: "POST",
    headers: { "Idempotency-Key": request.clientRequestId },
    body: jsonBody(request),
  });
}

export function deleteProject(projectId: string): Promise<void> {
  return creatorRequest(`/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    headers: { "Idempotency-Key": newClientId("delete-project") },
  });
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, sortJson(child)]),
    );
  }
  return value;
}

async function sha256(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return `sha256:${Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("")}`;
}

/** Match backend services.project_files.json_pointer.hash_json_value. */
export function hashProjectValue(
  value: unknown,
  missing = false,
): Promise<string> {
  return sha256(missing ? "MISSING" : JSON.stringify(sortJson(value)));
}

export function patchProject(
  projectId: string,
  request: ProjectPatchRequest,
): Promise<ProjectPatchResponse> {
  return creatorRequest(`/projects/${encodeURIComponent(projectId)}/project`, {
    method: "PATCH",
    headers: { "Idempotency-Key": request.clientCommandId },
    body: jsonBody(request),
  });
}
