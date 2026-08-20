import type { CreatorApiError } from "@/contracts/creator";
import i18n from "@/i18n";

export const CREATOR_API_BASE = "/api/qwenpaw-creator";

type HostWindow = Window & {
  QwenPaw?: { host?: { getApiToken?: () => string } };
};

export class CreatorHttpError extends Error {
  readonly status: number;
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
  try {
    body = (await response.json()) as Partial<CreatorApiError>;
  } catch {
    body = { message: response.statusText };
  }
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
    return await fetch(creatorApiUrl(path), { ...init, headers, signal });
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

export async function creatorRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { timeoutMs?: number } = {},
): Promise<T> {
  const response = await creatorFetch(path, init, options);
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}
