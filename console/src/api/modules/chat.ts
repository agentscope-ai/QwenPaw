import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  ChatSpec,
  ChatHistory,
  ChatRuntimeStatus,
  ChatDeleteResponse,
  Session,
} from "../types";

/** Response from POST /console/upload. url = filename only; agent_id from header. */
export interface ChatUploadResponse {
  url: string;
  file_name: string;
  stored_name?: string;
}

const CONSOLE_FILES_PREFIX = "/console/files";

function getSelectedAgentId(): string {
  try {
    const agentStorage = sessionStorage.getItem("copaw-agent-storage");
    if (agentStorage) {
      const parsed = JSON.parse(agentStorage);
      const id = parsed?.state?.selectedAgent;
      if (id) return id;
    }
  } catch {
    // ignore
  }
  return "";
}

export const chatApi = {
  /** Start a console chat stream with an initial user prompt. */
  startConsoleChat: async (params: {
    sessionId: string;
    prompt: string;
    userId?: string;
    channel?: string;
  }): Promise<void> => {
    const response = await fetch(getApiUrl("/console/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...buildAuthHeaders(),
      },
      body: JSON.stringify({
        input: [
          {
            role: "user",
            type: "message",
            content: [{ type: "text", text: params.prompt }],
          },
        ],
        session_id: params.sessionId,
        user_id: params.userId || "default",
        channel: params.channel || "console",
        stream: false,
      }),
    });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Failed to start console chat: ${response.status} ${response.statusText}${
          text ? ` - ${text}` : ""
        }`,
      );
    }

    // Drain stream response to completion. In pipeline bootstrap flow, if the
    // stream is left unread, backend persistence may stay in `running` with
    // empty history for a long time in some runtimes.
    if (!response.body) {
      return;
    }

    // Keep draining in background so pipeline page can navigate immediately.
    void (async () => {
      const reader = response.body!.getReader();
      try {
        while (true) {
          const { done } = await reader.read();
          if (done) {
            break;
          }
        }
      } catch {
        // Swallow background drain errors; caller has already started the run.
      } finally {
        reader.releaseLock();
      }
    })();
  },

  /** Upload a file for chat attachment. Returns URL path for content. */
  uploadFile: async (file: File): Promise<ChatUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(getApiUrl("/console/upload"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText}${
          text ? ` - ${text}` : ""
        }`,
      );
    }
    return response.json();
  },

  /** Build full API URL for a console file. Backend returns filename only; agent_id from header/context (selectedAgent). */
  fileUrl: (filename: string): string => {
    if (!filename) return "";
    if (filename.startsWith("http://") || filename.startsWith("https://"))
      return filename;
    const agentId = getSelectedAgentId() || "default";
    const path = `${CONSOLE_FILES_PREFIX}/${agentId}/${filename.replace(
      /^\/+/,
      "",
    )}`;
    return getApiUrl(path);
  },
  listChats: (params?: { user_id?: string; channel?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append("user_id", params.user_id);
    if (params?.channel) searchParams.append("channel", params.channel);
    const query = searchParams.toString();
    return request<ChatSpec[]>(`/chats${query ? `?${query}` : ""}`);
  },

  createChat: (chat: Partial<ChatSpec>) =>
    request<ChatSpec>("/chats", {
      method: "POST",
      body: JSON.stringify(chat),
    }),

  getChat: (chatId: string, params?: { offset?: number; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (typeof params?.offset === "number") {
      searchParams.append("offset", String(params.offset));
    }
    if (typeof params?.limit === "number") {
      searchParams.append("limit", String(params.limit));
    }
    const query = searchParams.toString();
    return request<ChatHistory>(
      `/chats/${encodeURIComponent(chatId)}${query ? `?${query}` : ""}`,
    );
  },

  getRuntimeStatus: (chatId: string) =>
    request<ChatRuntimeStatus>(
      `/console/chats/${encodeURIComponent(chatId)}/runtime-status`,
    ),

  updateChat: (chatId: string, chat: Partial<ChatSpec>) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "PUT",
      body: JSON.stringify(chat),
    }),

  clearChatMeta: async (
    chatId: string,
    fallback?: { user_id?: string; channel?: string },
  ) => {
    const chats = await request<ChatSpec[]>(
      `/chats?${new URLSearchParams({
        ...(fallback?.user_id ? { user_id: fallback.user_id } : {}),
        ...(fallback?.channel ? { channel: fallback.channel } : {}),
      }).toString()}`,
    );

    const target = chats.find((chat) => chat.id === chatId);
    if (!target) {
      throw new Error(`Chat not found when clearing meta: ${chatId}`);
    }

    return request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "PUT",
      body: JSON.stringify({
        id: target.id,
        session_id: target.session_id,
        user_id: target.user_id,
        channel: target.channel,
        name: target.name,
        meta: {},
      }),
    });
  },

  deleteChat: (chatId: string) =>
    request<ChatDeleteResponse>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "DELETE",
    }),

  batchDeleteChats: (chatIds: string[]) =>
    request<{ success: boolean; deleted_count: number }>(
      "/chats/batch-delete",
      {
        method: "POST",
        body: JSON.stringify(chatIds),
      },
    ),

  stopChat: (chatId: string) =>
    request<void>(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
      method: "POST",
    }),

  // Backward-compatible alias used by existing chat page code.
  stopConsoleChat: (chatId: string) =>
    request<void>(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
      method: "POST",
    }),
};

export const sessionApi = {
  listSessions: (params?: { user_id?: string; channel?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append("user_id", params.user_id);
    if (params?.channel) searchParams.append("channel", params.channel);
    const query = searchParams.toString();
    return request<Session[]>(`/chats${query ? `?${query}` : ""}`);
  },

  getSession: (sessionId: string, params?: { offset?: number; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (typeof params?.offset === "number") {
      searchParams.append("offset", String(params.offset));
    }
    if (typeof params?.limit === "number") {
      searchParams.append("limit", String(params.limit));
    }
    const query = searchParams.toString();
    return request<ChatHistory>(
      `/chats/${encodeURIComponent(sessionId)}${query ? `?${query}` : ""}`,
    );
  },

  deleteSession: (sessionId: string) =>
    request<ChatDeleteResponse>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),

  createSession: (session: Partial<Session>) =>
    request<Session>("/chats", {
      method: "POST",
      body: JSON.stringify(session),
    }),

  updateSession: (sessionId: string, session: Partial<Session>) =>
    request<Session>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "PUT",
      body: JSON.stringify(session),
    }),

  batchDeleteSessions: (sessionIds: string[]) =>
    request<{ success: boolean; deleted_count: number }>(
      "/chats/batch-delete",
      {
        method: "POST",
        body: JSON.stringify(sessionIds),
      },
    ),
};
