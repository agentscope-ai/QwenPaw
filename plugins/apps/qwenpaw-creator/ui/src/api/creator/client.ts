import type { CreatorApiError } from "@/contracts/creator";
import i18n from "@/i18n";
import {
  reportBackendAvailable,
  reportBackendUnavailable,
} from "@/lib/backendHealthSignal";

export const CREATOR_API_BASE = "/api/qwenpaw-creator";

type HostWindow = Window & {
  QwenPaw?: {
    host?: {
      getApiToken?: () => string;
      usesBrowserSession?: (appId: string) => boolean;
    };
  };
};

export class CreatorHttpError extends Error {
  readonly status: number;
  readonly userMessage: string;
  readonly code: string;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;
  readonly errorId?: string;
  readonly traceId?: string;
  readonly requestId?: string;

  constructor(status: number, error: Partial<CreatorApiError> = {}) {
    const message = error.message || i18n.t("api.requestFailed", { status });
    super(
      error.errorId ? `${message} （错误编号：${error.errorId}）` : message,
    );
    this.name = "CreatorHttpError";
    this.userMessage = message;
    this.status = status;
    this.code = error.code || `HTTP_${status}`;
    this.retryable = error.retryable ?? false;
    this.details = error.details ?? {};
    this.errorId = error.errorId;
    this.traceId = error.traceId;
    this.requestId = error.requestId;
  }
}

export function creatorApiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${CREATOR_API_BASE}${normalized}`;
}

/**
 * Build a Creator URL usable by EventSource and DOM media elements, which
 * cannot send an Authorization header. Appends the host token as a `token`
 * query parameter, matching the QwenPaw AuthMiddleware contract.
 */
export function creatorAuthenticatedUrl(path: string): string {
  const url = creatorApiUrl(path);
  const host = (window.parent as HostWindow).QwenPaw?.host;
  if (host?.usesBrowserSession?.("qwenpaw-creator")) return url;
  const token = hostToken();
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}

function secureRandomHex(byteLength = 8): string {
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function newClientId(prefix = "client"): string {
  const id =
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${secureRandomHex()}`;
  return `${prefix}-${id}`;
}

export function hostToken(): string | null {
  try {
    const current = window as HostWindow;
    const parent = window.parent as HostWindow;
    return (
      parent?.QwenPaw?.host?.getApiToken?.() ||
      current.QwenPaw?.host?.getApiToken?.() ||
      null
    );
  } catch {
    return null;
  }
}

export function creatorHeaders(initial?: HeadersInit): Headers {
  const headers = new Headers(initial);
  const token = hostToken();
  if (token && !headers.has("Authorization"))
    headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

async function errorFrom(response: Response): Promise<CreatorHttpError> {
  let body: Partial<CreatorApiError> = {};
  let parsedEnvelope = false;
  try {
    body = (await response.json()) as Partial<CreatorApiError>;
    parsedEnvelope =
      body != null &&
      typeof body === "object" &&
      (typeof body.code === "string" ||
        typeof body.message === "string" ||
        typeof (body as { detail?: unknown }).detail !== "undefined");
  } catch {
    body = {};
  }
  // The host SPA catch-all answers unmatched methods on an unloaded plugin
  // route with a plain-text 405 "Method Not Allowed" (v2.0.6: users saw a raw
  // English HTTP status when the Creator backend failed to load after an
  // upgrade). A 404 outside the Creator error envelope means the same thing.
  // A structured 405 from the real backend (e.g. FastAPI's
  // {"detail":"Method Not Allowed"} for a wrong method) is a genuine client
  // error, not an unloaded plugin, so both statuses require a non-envelope
  // body before being translated into a "backend not loaded" diagnostic.
  if ((response.status === 404 || response.status === 405) && !parsedEnvelope) {
    reportBackendUnavailable();
    return new CreatorHttpError(response.status, {
      code: "BACKEND_UNAVAILABLE",
      message: i18n.t("api.backendUnavailable"),
      retryable: true,
    });
  }
  if (!parsedEnvelope && !body.message) body = { message: response.statusText };
  body.errorId ??= response.headers?.get?.("X-Creator-Error-ID") ?? undefined;
  body.traceId ??= response.headers?.get?.("X-Creator-Trace-ID") ?? undefined;
  body.requestId ??= response.headers?.get?.("X-Request-ID") ?? undefined;
  if (!body.message) {
    // Keep compatibility with older hosts that still return FastAPI's raw
    // `detail` payload instead of the Creator diagnostic envelope.
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") {
      body = { ...body, message: detail };
    } else if (Array.isArray(detail)) {
      const message = detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: string };
          const loc = Array.isArray(entry.loc)
            ? entry.loc.filter((part) => part !== "body").join(".")
            : "";
          return loc ? `${loc}: ${entry.msg ?? ""}` : entry.msg ?? "";
        })
        .filter(Boolean)
        .join("; ");
      if (message) body = { ...body, message };
    }
  }
  return new CreatorHttpError(response.status, body);
}

/** Perform an authenticated Creator request without interpreting its status. */
export async function creatorFetch(
  path: string,
  init: RequestInit = {},
  options: { timeoutMs?: number } = {},
): Promise<Response> {
  const headers = creatorHeaders(init.headers);
  const requestId = headers.get("X-Request-ID") || newClientId("request");
  headers.set("X-Request-ID", requestId);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  let signal = init.signal ?? undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  if (options.timeoutMs && options.timeoutMs > 0) {
    const controller = new AbortController();
    timer = setTimeout(() => controller.abort(), options.timeoutMs);
    if (init.signal) {
      const upstream = init.signal;
      if (upstream.aborted) controller.abort();
      else upstream.addEventListener("abort", () => controller.abort());
    }
    signal = controller.signal;
  }
  try {
    const response = await fetch(creatorApiUrl(path), {
      ...init,
      headers,
      signal,
    });
    // A real Creator response proves the backend is mounted. A 405 is only
    // proof of the opposite when it did not come from the plugin's JSON API
    // (the host SPA catch-all answers the unloaded route in plain text/HTML).
    if (response.ok) reportBackendAvailable();
    else if (response.status === 405) {
      const contentType = response.headers?.get?.("Content-Type") ?? "";
      if (!contentType.includes("application/json")) reportBackendUnavailable();
    }
    return response;
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    throw new CreatorHttpError(aborted ? 408 : 0, {
      code: aborted ? "CLIENT_TIMEOUT" : "NETWORK_ERROR",
      message: aborted
        ? i18n.t("api.requestFailed", { status: 408 })
        : error instanceof Error
        ? error.message
        : i18n.t("api.requestFailed", { status: 0 }),
      retryable: true,
      details: { path, requestId },
      requestId,
    });
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

async function creatorFetchJson<T>(
  path: string,
  init: RequestInit,
  options: { timeoutMs?: number; dedupe?: boolean },
): Promise<T> {
  const response = await creatorFetch(path, init, options);
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/**
 * In-flight GETs share one request.
 *
 * Opening a Project page issued the same read several times over -- the
 * execution-authorization lookup five times, the active-review lookup three,
 * the Project document three, and tts-capabilities three on the way back. A
 * duplicate is not merely a wasted round trip: every one of them costs the
 * server a document load inside a process whose GIL measured 96% busy, so
 * duplicates actively slow down the request that matters.
 *
 * Only signal-free GETs join a shared promise. Aborting a shared request would
 * fail callers that never asked to cancel, so a caller that passes its own
 * signal gets its own request -- which is exactly what cancellation needs.
 *
 * ``dedupe: false`` opts out for callers that must observe two independent
 * responses; the store's refresh-ordering test is one of them.
 */
const inflightGets = new Map<string, Promise<unknown>>();

// A caller joining a shared GET observes the original snapshot boundary. SSE
// projections can use that boundary to protect changes received in the meantime.
let issuedRead = 0;
const readSequences = new WeakMap<Promise<unknown>, number>();
export function invalidateCreatorListReads(path: string): void {
  // A mutation makes earlier reads of this collection stale, in every sort order.
  for (const key of inflightGets.keys()) {
    if (key.startsWith(path + "?") || key.startsWith(path + "|")) {
      inflightGets.delete(key);
    }
  }
}

export function creatorReadSequence(request?: Promise<unknown>): number {
  return request ? readSequences.get(request) ?? 0 : issuedRead;
}

export function creatorRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { timeoutMs?: number; dedupe?: boolean } = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  if (
    method !== "GET" ||
    init.body ||
    init.signal ||
    options.dedupe === false
  ) {
    const request = creatorFetchJson<T>(path, init, options);
    if (method === "GET") readSequences.set(request, ++issuedRead);
    return request;
  }
  const key = `${path}|${options.timeoutMs ?? 0}`;
  const shared = inflightGets.get(key);
  if (shared) return shared as Promise<T>;
  const created = creatorFetchJson<T>(path, init, options).finally(() => {
    if (inflightGets.get(key) === created) inflightGets.delete(key);
  });
  readSequences.set(created, ++issuedRead);
  inflightGets.set(key, created);
  return created;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}
