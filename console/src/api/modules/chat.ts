import { request } from "../request";
import type {
  ChatSpec,
  ChatHistory,
  ChatDeleteResponse,
  Session,
} from "../types";

export const chatApi = {
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

  updateChat: (chatId: string, chat: Partial<ChatSpec>) =>
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
