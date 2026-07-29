import type {
  CreatorApiError,
  FileProjectChangeKind,
  FileProjectReviewDecisionRequest,
  FileProjectReviewOperation,
  FileProjectReviewOperationDecision,
  FileProjectReviewPollResult,
  FileProjectReviewRecord,
  FileProjectReviewStatus,
} from "@/contracts/creator";
import { CreatorHttpError, creatorFetch, jsonBody } from "./client";

const CHANGE_KINDS = new Set<FileProjectChangeKind>([
  "create",
  "update",
  "delete",
  "move",
  "reorder",
  "select_asset",
]);
const REVIEW_STATUSES = new Set<FileProjectReviewStatus>([
  "PENDING",
  "RESOLVED",
  "SUPERSEDED",
]);
const OPERATION_DECISIONS = new Set<FileProjectReviewOperationDecision>([
  "PENDING",
  "ACCEPTED",
  "REJECTED",
  "REVISED",
  "SUPERSEDED_BY_USER_EDIT",
]);

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function generation(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function stringRecord(value: unknown): value is Record<string, string> {
  const candidate = record(value);
  return (
    candidate !== null &&
    Object.values(candidate).every((item) => typeof item === "string")
  );
}

function parseOperation(value: unknown): FileProjectReviewOperation {
  const item = record(value);
  if (
    !item ||
    !CHANGE_KINDS.has(item.kind as FileProjectChangeKind) ||
    !nullableString(item.json_pointer) ||
    !nullableString(item.file_id) ||
    !nullableString(item.target_ref) ||
    !nonEmptyString(item.before_hash) ||
    !nonEmptyString(item.after_hash) ||
    !Object.hasOwn(item, "before") ||
    !Object.hasOwn(item, "after") ||
    !nonEmptyString(item.operation_id) ||
    !stringRecord(item.ui_locator) ||
    !OPERATION_DECISIONS.has(
      item.decision as FileProjectReviewOperationDecision,
    )
  ) {
    throw new Error("File Project Review operation response is malformed");
  }
  if (
    item.json_pointer === null &&
    item.file_id === null &&
    item.target_ref === null
  ) {
    throw new Error("File Project Review operation has no locator");
  }
  if (item.json_pointer !== null && !item.json_pointer.startsWith("/")) {
    throw new Error("File Project Review JSON Pointer is malformed");
  }
  return item as unknown as FileProjectReviewOperation;
}

export function parseFileProjectReview(
  value: unknown,
): FileProjectReviewRecord {
  const item = record(value);
  if (
    !item ||
    !nonEmptyString(item.review_id) ||
    !nonEmptyString(item.round_id) ||
    // request_id / request_message_seq / interrupted_run_id are only present
    // for AgentDock-originated reviews; media/runtime reviews leave them null.
    !nullableString(item.request_id) ||
    !(
      item.request_message_seq === null ||
      (Number.isInteger(item.request_message_seq) &&
        Number(item.request_message_seq) >= 1)
    ) ||
    !nullableString(item.interrupted_run_id) ||
    !generation(item.baseline_generation) ||
    !nonEmptyString(item.baseline_etag) ||
    !generation(item.candidate_generation) ||
    Number(item.candidate_generation) < Number(item.baseline_generation) ||
    !nonEmptyString(item.candidate_etag) ||
    !nonEmptyString(item.decision_token) ||
    !REVIEW_STATUSES.has(item.status as FileProjectReviewStatus) ||
    !Array.isArray(item.operations) ||
    item.operations.length === 0 ||
    !nonEmptyString(item.created_at) ||
    !nonEmptyString(item.updated_at)
  ) {
    throw new Error("File Project Review response is malformed");
  }
  const operations = item.operations.map(parseOperation);
  const operationIds = new Set(
    operations.map((operation) => operation.operation_id),
  );
  if (operationIds.size !== operations.length) {
    throw new Error("File Project Review contains duplicate operation IDs");
  }
  const hasPending = operations.some(
    (operation) => operation.decision === "PENDING",
  );
  if (
    (item.status === "PENDING" && !hasPending) ||
    (item.status === "RESOLVED" && hasPending)
  ) {
    throw new Error("File Project Review status does not match its operations");
  }
  return { ...item, operations } as unknown as FileProjectReviewRecord;
}

function semanticEtag(value: string): string {
  return value.trim().replace(/^W\//, "").replace(/^"|"$/g, "");
}

async function httpError(response: Response): Promise<CreatorHttpError> {
  let body: Partial<CreatorApiError> = {};
  try {
    body = (await response.json()) as Partial<CreatorApiError>;
  } catch {
    body = { message: response.statusText };
  }
  return new CreatorHttpError(response.status, body);
}

export async function getActiveFileProjectReview(
  projectId: string,
  etag?: string | null,
): Promise<FileProjectReviewPollResult> {
  const headers = new Headers();
  if (etag) headers.set("If-None-Match", etag);
  const response = await creatorFetch(
    `/projects/${encodeURIComponent(projectId)}/runtime/reviews/active`,
    // The poller manages If-None-Match/ETag itself; bypass the browser HTTP
    // cache so a stale body cached by an old deployment is never re-parsed as
    // fresh data on a 304 reuse.
    { headers, cache: "no-store" },
    { timeoutMs: 30_000 },
  );
  const responseEtag = response.headers?.get("ETag") ?? null;

  if (response.status === 304) {
    return { kind: "not_modified", etag: responseEtag ?? etag ?? null };
  }
  if (response.status === 204) return { kind: "empty" };
  if (!response.ok) throw await httpError(response);

  const payload = await response.json();
  if (!Array.isArray(payload)) {
    throw new Error("File Project Review response is not an array");
  }
  const reviews = payload.map(parseFileProjectReview);
  if (!responseEtag) {
    throw new Error("File Project Review response is missing ETag");
  }
  const compositeToken = reviews.map((r) => r.decision_token).join("|");
  if (semanticEtag(responseEtag) !== semanticEtag(compositeToken)) {
    throw new Error("File Project Review ETag does not match decision_tokens");
  }
  return { kind: "updated", reviews, etag: responseEtag };
}

export async function decideFileProjectReview(
  projectId: string,
  reviewId: string,
  request: FileProjectReviewDecisionRequest,
  idempotencyKey = request.decisionId,
): Promise<FileProjectReviewRecord> {
  const response = await creatorFetch(
    `/projects/${encodeURIComponent(projectId)}/runtime/reviews/` +
      `${encodeURIComponent(reviewId)}/decisions`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: jsonBody(request),
    },
  );
  if (!response.ok) throw await httpError(response);
  return parseFileProjectReview(await response.json());
}
