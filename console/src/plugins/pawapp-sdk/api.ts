/**
 * pawapp-sdk/api.ts — Backend API communication for PawApps.
 *
 * In same-origin mode (M0-M2), this delegates to `hostFetch` which
 * adds auth headers automatically. No iframe postMessage needed.
 */
import { hostFetch } from "../hostSdk/fetch";
import type { PawRequestOptions, PawTaskHandle } from "./types";
import { createPawTask } from "./task";

/** Get the current PawApp ID from page context. */
function getAppId(): string {
  // Extract app_id from URL: /apps/{app_id}/...
  const match = window.location.pathname.match(/\/apps\/([^/]+)/);
  return match?.[1] ?? "";
}

/** Build the full API path for a PawApp endpoint. */
function buildPath(path: string): string {
  const appId = getAppId();
  // Normalize: ensure path starts with /
  const normalized = path.startsWith("/") ? path : `/${path}`;
  // PawApp routes are registered at /api/{app_id}/... by PawApp.register()
  return `/${appId}${normalized}`;
}

/**
 * POST request to PawApp backend.
 */
export async function post<T = unknown>(
  path: string,
  body?: unknown,
  opts?: PawRequestOptions,
): Promise<T> {
  const res = await hostFetch(buildPath(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...opts?.headers,
    },
    body: body != null ? JSON.stringify(body) : undefined,
    signal: opts?.signal,
  });
  if (!res.ok) {
    throw new Error(`PawApp API error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

/**
 * GET request to PawApp backend.
 */
export async function get<T = unknown>(
  path: string,
  opts?: PawRequestOptions,
): Promise<T> {
  const res = await hostFetch(buildPath(path), {
    method: "GET",
    headers: opts?.headers,
    signal: opts?.signal,
  });
  if (!res.ok) {
    throw new Error(`PawApp API error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

/**
 * Streaming response (Server-Sent Events style line reader).
 */
export async function* stream(
  path: string,
  body?: unknown,
  opts?: PawRequestOptions,
): AsyncGenerator<string> {
  const res = await hostFetch(buildPath(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...opts?.headers,
    },
    body: body != null ? JSON.stringify(body) : undefined,
    signal: opts?.signal,
  });

  if (!res.ok) {
    throw new Error(`PawApp stream error ${res.status}: ${res.statusText}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body for stream");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        yield line.slice(6);
      }
    }
  }

  // Flush remaining buffer
  if (buffer.startsWith("data: ")) {
    yield buffer.slice(6);
  }
}

/**
 * Create a long-running task with SSE event stream.
 */
export function task(path: string, params?: unknown): PawTaskHandle {
  const appId = getAppId();
  return createPawTask(appId, path, params);
}

/** The paw.api namespace object. */
export const apiNamespace = {
  post,
  get,
  stream,
  task,
};
