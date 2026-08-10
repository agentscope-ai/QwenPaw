/**
 * pawapp-sdk/host.ts — Host capability wrappers for PawApps.
 *
 * Provides `paw.chat()`, `paw.storage`, `paw.toast()`, `paw.notify()`
 * which delegate to the host's existing QwenPaw namespace and APIs.
 */
import { hostFetch } from "../hostSdk/fetch";
import type { PawChatOptions, PawStorageApi } from "./types";
import { getActivePawAppId } from "./context";
import { createApiNamespace } from "./api";
import type { PawHostNamespace } from "./types";

/** Get the current PawApp ID from page context. */
function getAppId(): string {
  return getActivePawAppId();
}

/**
 * Send a chat message to the Agent and get a text reply.
 */
export async function chat(
  message: string,
  options: PawChatOptions = {},
): Promise<string> {
  // Use unified route: /{appId}/... -> /api/{appId}/... via hostFetch
  const agentId =
    options.agentId ??
    window.QwenPaw.host?.getSelectedAgentId?.() ??
    "default";
  const sessionId =
    options.sessionId === undefined
      ? window.QwenPaw.host?.getCurrentSessionId?.() ?? undefined
      : options.sessionId ?? undefined;
  const query = new URLSearchParams({ agent_id: agentId }).toString();
  const res = await hostFetch(`/${getAppId()}/chat?${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      skill: options.skill,
    }),
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

export function createHostNamespace(
  appIdProvider: () => string,
): PawHostNamespace {
  const api = createApiNamespace(appIdProvider);
  const scopedStorage: PawStorageApi = {
    get: async <T = unknown>(key: string, defaultValue?: T) => {
      try {
        const data = await api.get<{ value?: T }>(
          `/storage/${encodeURIComponent(key)}`,
        );
        return data.value ?? (defaultValue as T);
      } catch {
        return defaultValue as T;
      }
    },
    set: async (key, value) => {
      await api.put(`/storage/${encodeURIComponent(key)}`, { value });
    },
    delete: async (key) => {
      await api.delete(`/storage/${encodeURIComponent(key)}`);
    },
    keys: async () => {
      const data = await api.get<{ keys?: string[] }>("/storage");
      return data.keys ?? [];
    },
  };

  return {
    async chat(message, options = {}) {
      const agentId =
        options.agentId ??
        window.QwenPaw.host?.getSelectedAgentId?.() ??
        "default";
      const sessionId =
        options.sessionId === undefined
          ? window.QwenPaw.host?.getCurrentSessionId?.() ?? undefined
          : options.sessionId ?? undefined;
      const data = await api.post<{ text?: string; reply?: string }>(
        "/chat",
        { message, session_id: sessionId, skill: options.skill },
        { query: { agent_id: agentId } },
      );
      return data.text ?? data.reply ?? "";
    },
    storage: scopedStorage,
    getSelectedAgentId: () =>
      window.QwenPaw.host?.getSelectedAgentId?.() ?? "default",
    getCurrentSessionId: () =>
      window.QwenPaw.host?.getCurrentSessionId?.() ?? null,
    async toast(message, kind = "info") {
      const host = window.QwenPaw.host as {
        toast?: (m: string, k: string) => void;
      };
      if (host?.toast) {
        host.toast(message, kind);
        return;
      }
      await api.post("/toast", { message, kind });
    },
    async notify(title, body) {
      await api.post("/notify", { title, body });
    },
  };
}

/** The paw.host namespace. */
export const hostNamespace = {
  chat,
  storage,
  getSelectedAgentId: () =>
    window.QwenPaw.host?.getSelectedAgentId?.() ?? "default",
  getCurrentSessionId: () =>
    window.QwenPaw.host?.getCurrentSessionId?.() ?? null,
  toast,
  notify,
};
