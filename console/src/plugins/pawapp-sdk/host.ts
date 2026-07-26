/**
 * pawapp-sdk/host.ts — Host capability wrappers for PawApps.
 *
 * Provides `paw.chat()`, `paw.storage`, `paw.toast()`, `paw.notify()`
 * which delegate to the host's existing QwenPaw namespace and APIs.
 */
import { hostFetch } from "../hostSdk/fetch";
import type { PawStorageApi } from "./types";

/** Get the current PawApp ID from page context. */
function getAppId(): string {
  const match = window.location.pathname.match(/\/apps\/([^/]+)/);
  return match?.[1] ?? "";
}

/**
 * Send a chat message to the Agent and get a text reply.
 */
export async function chat(message: string): Promise<string> {
  // Use unified route: /{appId}/... -> /api/{appId}/... via hostFetch
  const res = await hostFetch(`/${getAppId()}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    throw new Error(`Chat failed: ${res.status} ${res.statusText}`);
  }

  const data = await res.json();
  return data.text ?? data.reply ?? "";
}

/**
 * App-namespaced key-value storage.
 */
export const storage: PawStorageApi = {
  async get<T = unknown>(key: string, defaultValue?: T): Promise<T> {
    // Use unified route: /{appId}/... -> /api/{appId}/... via hostFetch
    const res = await hostFetch(
      `/${getAppId()}/storage/${encodeURIComponent(key)}`,
      { method: "GET" },
    );
    if (!res.ok) {
      return defaultValue as T;
    }
    const data = await res.json();
    return (data.value ?? defaultValue) as T;
  },

  async set(key: string, value: unknown): Promise<void> {
    await hostFetch(`/${getAppId()}/storage/${encodeURIComponent(key)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
  },

  async delete(key: string): Promise<void> {
    await hostFetch(`/${getAppId()}/storage/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
  },

  async keys(): Promise<string[]> {
    const res = await hostFetch(`/${getAppId()}/storage`, {
      method: "GET",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.keys ?? [];
  },
};

/**
 * Show a toast notification in the host UI.
 */
export async function toast(
  message: string,
  kind: "info" | "success" | "warning" | "error" = "info",
): Promise<void> {
  // Use QwenPaw host notification if available (same-origin)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const qwenpaw = (window as any).QwenPaw as
    | Record<string, unknown>
    | undefined;
  if (qwenpaw?.host) {
    const host = qwenpaw.host as {
      toast?: (msg: string, kind: string) => void;
    };
    if (host.toast) {
      host.toast(message, kind);
      return;
    }
  }
  // Fallback: POST to backend which pushes via SSE
  await hostFetch(`/${getAppId()}/toast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, kind }),
  });
}

/**
 * Send a notification (multi-channel).
 */
export async function notify(title: string, body?: string): Promise<void> {
  await hostFetch(`/${getAppId()}/notify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body }),
  });
}

/** The paw.host namespace. */
export const hostNamespace = {
  chat,
  storage,
  toast,
  notify,
};
