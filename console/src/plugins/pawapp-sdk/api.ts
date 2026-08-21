/**
 * pawapp-sdk/api.ts — Backend API communication for PawApps.
 *
 * In same-origin mode (M0-M2), this delegates to `hostFetch` which
 * adds auth headers automatically. No iframe postMessage needed.
 */
import { hostFetch } from "../hostSdk/fetch";
import type {
  PawApiNamespace,
  PawRequestInit,
  PawRequestOptions,
  PawSseEvent,
  PawSseOptions,
  PawTaskHandle,
} from "./types";
import { createPawTask, createScopedPawTask } from "./task";
import { getActivePawAppId } from "./context";
import { normalizeAppId, normalizeAppRelativePath } from "./scope";

export class PawApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;

  constructor(
    status: number,
    message: string,
    options: { code?: string; detail?: unknown } = {},
  ) {
    super(`PawApp API error ${status}: ${message}`);
    this.name = "PawApiError";
    this.status = status;
    this.code = options.code;
    this.detail = options.detail;
  }
}

/** Get the current PawApp ID from page context. */
function getAppId(): string {
  return getActivePawAppId();
}

/** Build the full API path for a PawApp endpoint. */
function buildPath(
  path: string,
  appId: string,
  query?: PawRequestOptions["query"],
  strictScope = true,
): string {
  const normalized = strictScope
    ? normalizeAppRelativePath(path)
    : path.startsWith("/")
    ? path
    : `/${path}`;
  // PawApp routes are registered at /api/{app_id}/... by PawApp.register()
  const base = `/${strictScope ? normalizeAppId(appId) : appId}${normalized}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const encoded = params.toString();
  if (!encoded) return base;
  return `${base}${base.includes("?") ? "&" : "?"}${encoded}`;
}

async function parseResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    let code: string | undefined;
    let rawDetail: unknown = text;
    try {
      const parsed = JSON.parse(text) as {
        detail?: unknown;
        message?: unknown;
        code?: unknown;
      };
      const value = parsed.detail ?? parsed.message ?? parsed;
      rawDetail = value;
      if (typeof value === "object" && value !== null) {
        const structured = value as { code?: unknown; message?: unknown };
        if (typeof structured.code === "string") code = structured.code;
        if (typeof structured.message === "string") {
          detail = structured.message;
        } else {
          detail = JSON.stringify(value) || text;
        }
      } else {
        if (typeof parsed.code === "string") code = parsed.code;
        detail =
          typeof value === "string" ? value : JSON.stringify(value) || text;
      }
    } catch {
      // Preserve the response text when it is not JSON.
    }
    throw new PawApiError(res.status, detail || res.statusText, {
      code,
      detail: rawDetail,
    });
  }
  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return res.json();
  return (await res.text()) as T;
}

function createRequest(appIdProvider: () => string, strictScope: boolean) {
  return async function request<T = unknown>(
    path: string,
    opts: PawRequestInit = {},
  ): Promise<T> {
    const method = opts.method ?? "GET";
    const hasBody = opts.body !== undefined && opts.body !== null;
    const hasRawBody = opts.rawBody !== undefined && opts.rawBody !== null;
    if (hasBody && hasRawBody) {
      throw new Error("PawApp request cannot set both body and rawBody");
    }
    const res = await hostFetch(
      buildPath(path, appIdProvider(), opts.query, strictScope),
      {
        method,
        headers: {
          ...(hasBody ? { "Content-Type": "application/json" } : {}),
          ...opts.headers,
        },
        body: hasRawBody
          ? opts.rawBody
          : hasBody
          ? JSON.stringify(opts.body)
          : undefined,
        signal: opts.signal,
      },
    );
    return parseResponse<T>(res);
  };
}

function createApiNamespaceWithScope(
  appIdProvider: () => string,
  strictScope: boolean,
): PawApiNamespace {
  const request = createRequest(appIdProvider, strictScope);
  return {
    request,
    get: (path, opts) => request(path, { ...opts, method: "GET" }),
    post: (path, body, opts) =>
      request(path, { ...opts, method: "POST", body }),
    put: (path, body, opts) => request(path, { ...opts, method: "PUT", body }),
    patch: (path, body, opts) =>
      request(path, { ...opts, method: "PATCH", body }),
    delete: (path, opts) => request(path, { ...opts, method: "DELETE" }),
    async download(path, opts) {
      const res = await hostFetch(
        buildPath(path, appIdProvider(), opts?.query, strictScope),
        { method: "GET", headers: opts?.headers, signal: opts?.signal },
      );
      if (!res.ok) await parseResponse(res);
      return res.blob();
    },
    stream: (path, body, opts) =>
      streamForApp(appIdProvider, path, body, opts, strictScope),
    events: (path, opts) =>
      eventsForApp(appIdProvider, path, opts, strictScope),
    task: (path, params) =>
      strictScope
        ? createScopedPawTask(appIdProvider(), path, params)
        : createPawTask(appIdProvider(), path, params),
  };
}

/** Create a permanently scoped API namespace for a validated app ID. */
export function createApiNamespace(
  appIdProvider: () => string,
): PawApiNamespace {
  return createApiNamespaceWithScope(appIdProvider, true);
}

/**
 * POST request to PawApp backend.
 * @deprecated Use `pawSdkFactory.forApp(appId).api.post()`.
 */
export async function post<T = unknown>(
  path: string,
  body?: unknown,
  opts?: PawRequestOptions,
): Promise<T> {
  return legacyApi.post<T>(path, body, opts);
}

/**
 * GET request to PawApp backend.
 * @deprecated Use `pawSdkFactory.forApp(appId).api.get()`.
 */
export async function get<T = unknown>(
  path: string,
  opts?: PawRequestOptions,
): Promise<T> {
  return legacyApi.get<T>(path, opts);
}

/**
 * Streaming response (Server-Sent Events style line reader).
 * @deprecated Use `pawSdkFactory.forApp(appId).api.stream()`.
 */
async function* streamForApp(
  appIdProvider: () => string,
  path: string,
  body?: unknown,
  opts?: PawRequestOptions,
  strictScope = true,
): AsyncGenerator<string> {
  const options: PawSseOptions = {
    ...opts,
    method: "POST",
    body,
  };
  for await (const event of eventsForApp(
    appIdProvider,
    path,
    options,
    strictScope,
  )) {
    yield event.data;
  }
}

async function* eventsForApp(
  appIdProvider: () => string,
  path: string,
  opts: PawSseOptions = {},
  strictScope = true,
): AsyncGenerator<PawSseEvent> {
  const method = opts.method ?? "POST";
  const hasBody = opts.body !== undefined && opts.body !== null;
  const hasRawBody = opts.rawBody !== undefined && opts.rawBody !== null;
  if (hasBody && hasRawBody) {
    throw new Error("PawApp SSE request cannot set both body and rawBody");
  }
  if (method === "GET" && (hasBody || hasRawBody)) {
    throw new Error("PawApp GET SSE request cannot include a body");
  }
  const res = await hostFetch(
    buildPath(path, appIdProvider(), opts?.query, strictScope),
    {
      method,
      headers: {
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
        Accept: "text/event-stream",
        ...opts?.headers,
      },
      body: hasRawBody
        ? opts.rawBody
        : hasBody
        ? JSON.stringify(opts.body)
        : undefined,
      signal: opts?.signal,
    },
  );

  if (!res.ok) {
    await parseResponse(res);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body for stream");

  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];
  let eventId: string | undefined;
  let retry: number | undefined;

  function flush(): PawSseEvent | undefined {
    if (dataLines.length === 0) {
      eventName = "message";
      eventId = undefined;
      retry = undefined;
      return undefined;
    }
    const event: PawSseEvent = {
      event: eventName,
      data: dataLines.join("\n"),
      ...(eventId !== undefined ? { id: eventId } : {}),
      ...(retry !== undefined ? { retry } : {}),
    };
    eventName = "message";
    dataLines = [];
    eventId = undefined;
    retry = undefined;
    return event;
  }

  function consume(rawLine: string): PawSseEvent | undefined {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "") return flush();
    if (line.startsWith(":")) return undefined;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventName = value || "message";
    else if (field === "data") dataLines.push(value);
    else if (field === "id" && !value.includes("\0")) eventId = value;
    else if (field === "retry" && /^\d+$/.test(value)) retry = Number(value);
    return undefined;
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const event = consume(line);
        if (event) yield event;
      }
    }
    buffer += decoder.decode();
    if (buffer) {
      const event = consume(buffer);
      if (event) yield event;
    }
    const event = flush();
    if (event) yield event;
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

export async function* stream(
  path: string,
  body?: unknown,
  opts?: PawRequestOptions,
): AsyncGenerator<string> {
  yield* streamForApp(getAppId, path, body, opts, false);
}

/**
 * Create a long-running task with SSE event stream.
 * @deprecated Use `pawSdkFactory.forApp(appId).api.task()`.
 */
export function task(path: string, params?: unknown): PawTaskHandle {
  const appId = getAppId();
  return createPawTask(appId, path, params);
}

/** @deprecated Dynamic path-derived namespace retained for existing apps. */
const legacyApi = createApiNamespaceWithScope(getAppId, false);
/** @deprecated Use `pawSdkFactory.forApp(appId).api`. */
export const apiNamespace = legacyApi;
