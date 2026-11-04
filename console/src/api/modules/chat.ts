import { request } from "../request";
import { getApiUrl, getApiToken } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  ChatSpec,
  ChatHistory,
  ChatMessagePage,
  ChatUserMessagePage,
  ChatResolution,
  ChatDeleteResponse,
  ChatUpdateRequest,
  ChatGroup,
  BatchArchiveResult,
  Session,
} from "../types";

/** Response from POST /console/upload. url = filename only; agent_id from header. */
export interface ChatUploadResponse {
  url: string;
  file_name: string;
  stored_name?: string;
}

export interface ChatStatusResponse {
  status: "idle" | "running";
}

const FILES_PREVIEW = "/files/preview";

export const chatApi = {
  resolveChat: (
    chatId: string,
    options?: { currentAgentId?: string; signal?: AbortSignal },
  ) => {
    const params = new URLSearchParams({ chat_id: chatId });
    if (options?.currentAgentId)
      params.set("current_agent_id", options.currentAgentId);
    return request<ChatResolution>(`/chats/resolve?${params}`, {
      signal: options?.signal,
    });
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

  filePreviewUrl: (filename: string): string => {
    if (!filename) return "";
    if (filename.startsWith("http://") || filename.startsWith("https://"))
      return filename;
    const cleaned = filename.replace(/^\/+/, "");
    const path = `${FILES_PREVIEW}/${cleaned}`;
    const url = getApiUrl(path);

    const token = getApiToken();
    if (token) {
      return `${url}?token=${encodeURIComponent(token)}`;
    }

    return url;
  },
  listChats: (params?: {
    user_id?: string;
    channel?: string;
    archived?: boolean;
    include_app_owned?: boolean;
    agentId?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append("user_id", params.user_id);
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.archived !== undefined)
      searchParams.append("archived", String(params.archived));
    if (params?.include_app_owned !== undefined)
      searchParams.append(
        "include_app_owned",
        String(params.include_app_owned),
      );
    const query = searchParams.toString();
    const path = `/chats${query ? `?${query}` : ""}`;
    return params?.agentId
      ? request<ChatSpec[]>(path, {
          headers: { "X-Agent-Id": params.agentId },
        })
      : request<ChatSpec[]>(path);
  },

  createChat: (chat: Partial<ChatSpec>) =>
    request<ChatSpec>("/chats", {
      method: "POST",
      body: JSON.stringify(chat),
    }),

  forkCapability: (chatId: string, turnId: string, agentId?: string) =>
    request<{ can_fork: boolean; reason: string | null }>(
      `/chats/${encodeURIComponent(
        chatId,
      )}/fork-capability?turn_id=${encodeURIComponent(turnId)}`,
      { headers: agentId ? { "X-Agent-Id": agentId } : undefined },
    ),

  forkChat: (chatId: string, turnId: string, agentId?: string) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}/fork`, {
      method: "POST",
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
      body: JSON.stringify({ turn_id: turnId }),
    }),

  getChat: (
    chatId: string,
    options?: {
      signal?: AbortSignal;
      include_app_owned?: boolean;
      agentId?: string;
    },
  ) => {
    const searchParams = new URLSearchParams({ full_history: "false" });
    if (options?.include_app_owned !== undefined)
      searchParams.append(
        "include_app_owned",
        String(options.include_app_owned),
      );
    const query = searchParams.toString();
    return request<ChatHistory>(
      `/chats/${encodeURIComponent(chatId)}${query ? `?${query}` : ""}`,
      {
        signal: options?.signal,
        headers: options?.agentId
          ? { "X-Agent-Id": options.agentId }
          : undefined,
      },
    );
  },

  getChatStatus: (
    chatId: string,
    options?: { signal?: AbortSignal; agentId?: string },
  ) => {
    return request<ChatStatusResponse>(
      `/chats/${encodeURIComponent(chatId)}/status`,
      {
        signal: options?.signal,
        headers: options?.agentId
          ? { "X-Agent-Id": options.agentId }
          : undefined,
      },
    );
  },

  getChatMessages: (
    chatId: string,
    options?: {
      before?: string;
      wait_for_migration?: boolean;
      agentId?: string;
      after_message_id?: string;
      before_message_id?: string;
      limit?: number;
      signal?: AbortSignal;
      include_app_owned?: boolean;
    },
  ) => {
    const searchParams = new URLSearchParams();
    if (options?.before) searchParams.append("before", options.before);
    if (options?.before_message_id)
      searchParams.append("before_message_id", options.before_message_id);
    if (options?.after_message_id)
      searchParams.append("after_message_id", options.after_message_id);
    if (options?.limit !== undefined)
      searchParams.append("limit", String(options.limit));
    if (options?.include_app_owned !== undefined)
      searchParams.append(
        "include_app_owned",
        String(options.include_app_owned),
      );
    if (options?.wait_for_migration)
      searchParams.append("wait_for_migration", "true");
    const query = searchParams.toString();
    return request<ChatMessagePage>(
      `/chats/${encodeURIComponent(chatId)}/messages${
        query ? `?${query}` : ""
      }`,
      {
        signal: options?.signal,
        headers: options?.agentId
          ? { "X-Agent-Id": options.agentId }
          : undefined,
      },
    );
  },

  getChatUserMessageText: (
    chatId: string,
    messageId: string,
    signal?: AbortSignal,
  ) =>
    request<{ text: string }>(
      `/chats/${encodeURIComponent(chatId)}/user-messages/${encodeURIComponent(
        messageId,
      )}`,
      { signal },
    ),

  getChatUserMessages: (
    chatId: string,
    options?: {
      before?: string;
      limit?: number;
      signal?: AbortSignal;
      include_app_owned?: boolean;
    },
  ) => {
    const searchParams = new URLSearchParams();
    if (options?.before) searchParams.append("before", options.before);
    if (options?.limit !== undefined) {
      searchParams.append("limit", String(options.limit));
    }
    if (options?.include_app_owned !== undefined) {
      searchParams.append(
        "include_app_owned",
        String(options.include_app_owned),
      );
    }
    const query = searchParams.toString();
    return request<ChatUserMessagePage>(
      `/chats/${encodeURIComponent(chatId)}/user-messages${
        query ? `?${query}` : ""
      }`,
      { signal: options?.signal },
    );
  },

  updateChat: (chatId: string, chat: ChatUpdateRequest) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}`, {
      method: "PUT",
      body: JSON.stringify(chat),
    }),

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

  archiveChat: (chatId: string, agentId?: string) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}/archive`, {
      method: "POST",
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    }),

  unarchiveChat: (chatId: string, agentId?: string) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}/unarchive`, {
      method: "POST",
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    }),

  batchArchiveChats: (chatIds: string[], agentId?: string) =>
    request<BatchArchiveResult>("/chats/actions/batch-archive", {
      method: "POST",
      body: JSON.stringify({ chat_ids: chatIds }),
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    }),

  batchUnarchiveChats: (chatIds: string[], agentId?: string) =>
    request<BatchArchiveResult>("/chats/actions/batch-unarchive", {
      method: "POST",
      body: JSON.stringify({ chat_ids: chatIds }),
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    }),

  listGroups: () => request<ChatGroup[]>("/chats/groups"),

  createGroup: (name: string) =>
    request<ChatGroup>("/chats/groups", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  updateGroup: (groupId: string, update: { name?: string; pinned?: boolean }) =>
    request<ChatGroup>(`/chats/groups/${encodeURIComponent(groupId)}`, {
      method: "PUT",
      body: JSON.stringify(update),
    }),

  reorderGroups: (groupIds: string[]) =>
    request<ChatGroup[]>("/chats/groups/order", {
      method: "PUT",
      body: JSON.stringify({ group_ids: groupIds }),
    }),

  deleteGroup: (groupId: string) =>
    request<{ success: boolean; group_id: string }>(
      `/chats/groups/${encodeURIComponent(groupId)}`,
      { method: "DELETE" },
    ),

  stopChat: (chatId: string, agentId?: string) =>
    request<void>(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
      method: "POST",
      ...(agentId ? { headers: { "X-Agent-Id": agentId } } : {}),
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

  getSession: (sessionId: string) =>
    request<ChatHistory>(`/chats/${encodeURIComponent(sessionId)}`),

  deleteSession: (sessionId: string, agentId?: string) =>
    request<ChatDeleteResponse>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    }),

  createSession: (session: Partial<Session>) =>
    request<Session>("/chats", {
      method: "POST",
      body: JSON.stringify(session),
    }),

  updateSession: (
    sessionId: string,
    session: ChatUpdateRequest,
    agentId?: string,
  ) =>
    request<Session>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "PUT",
      body: JSON.stringify(session),
      headers: agentId ? { "X-Agent-Id": agentId } : undefined,
    }),

  batchDeleteSessions: (sessionIds: string[], agentId?: string) =>
    request<{ success: boolean; deleted_count: number }>(
      "/chats/batch-delete",
      {
        method: "POST",
        body: JSON.stringify(sessionIds),
        headers: agentId ? { "X-Agent-Id": agentId } : undefined,
      },
    ),
};
