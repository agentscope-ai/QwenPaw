import { request } from "../request";
import { getApiUrl, getApiToken } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  ChatSpec,
  ChatHistory,
  ChatDeleteResponse,
  ChatUpdateRequest,
  BatchArchiveResult,
  Session,
  ConversationMember,
  ConversationShareCandidate,
} from "../types";
import type {
  AttachmentLifecycle,
  AttachmentListItem,
} from "../../features/attachments/types";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./agentRequestContext";

/** Response from POST /console/upload. url = filename only; agent_id from header. */
export interface ChatUploadResponse {
  url: string;
  attachment_id?: string;
  file_name: string;
  stored_name?: string;
  size?: number;
}

export interface ChatStatusResponse {
  status: "idle" | "running";
}

const FILES_PREVIEW = "/files/preview";

const withApiToken = (url: string): string => {
  const token = getApiToken();
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(token)}`;
};

export const chatApi = {
  /** Upload a file for chat attachment. Returns URL path for content. */
  uploadFile: async (
    file: File,
    conversationId?: string,
  ): Promise<ChatUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    const query = conversationId
      ? `?conversation_id=${encodeURIComponent(conversationId)}`
      : "";
    const response = await fetch(getApiUrl(`/console/upload${query}`), {
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

  listAttachments: (params?: {
    lifecycle?: AttachmentLifecycle;
    conversationId?: string;
    requestContext?: AgentRequestContext;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.lifecycle) {
      searchParams.set("lifecycle", params.lifecycle);
    }
    if (params?.conversationId) {
      searchParams.set("conversation_id", params.conversationId);
    }
    const query = searchParams.toString();
    const path = `/console/attachments${query ? `?${query}` : ""}`;
    const options = withAgentRequestContext(undefined, params?.requestContext);
    return options
      ? request<AttachmentListItem[]>(path, options)
      : request<AttachmentListItem[]>(path);
  },
  saveAttachment: (attachmentId: string, targetPath?: string, context?: AgentRequestContext) =>
    request<AttachmentListItem>(`/console/attachments/${encodeURIComponent(attachmentId)}/save`, withAgentRequestContext({
      method: "POST",
      body: JSON.stringify({ target_path: targetPath ?? null }),
    }, context)),
  moveAttachment: (attachmentId: string, targetPath: string, context?: AgentRequestContext) =>
    request<AttachmentListItem>(`/console/attachments/${encodeURIComponent(attachmentId)}/move`, withAgentRequestContext({
      method: "POST",
      body: JSON.stringify({ target_path: targetPath }),
    }, context)),
  deleteAttachment: (attachmentId: string, context?: AgentRequestContext) =>
    request<AttachmentListItem>(`/console/attachments/${encodeURIComponent(attachmentId)}`, withAgentRequestContext({
      method: "DELETE",
    }, context)),

  filePreviewUrl: (filename: string): string => {
    if (!filename) return "";
    if (filename.startsWith("http://") || filename.startsWith("https://"))
      return filename;
    if (filename.startsWith("/api/console/attachments/")) {
      return withApiToken(getApiUrl(filename.slice("/api".length)));
    }
    let cleaned = filename.replace(/^\/+/, "");
    const path = `${FILES_PREVIEW}/${cleaned}`;
    return withApiToken(getApiUrl(path));
  },
  listChats: (params?: {
    user_id?: string;
    channel?: string;
    archived?: boolean;
    scope?: "all" | "owned" | "shared";
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.user_id) searchParams.append("user_id", params.user_id);
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.archived !== undefined)
      searchParams.append("archived", String(params.archived));
    if (params?.scope) searchParams.append("scope", params.scope);
    const query = searchParams.toString();
    return request<ChatSpec[]>(`/chats${query ? `?${query}` : ""}`);
  },

  createChat: (chat: Partial<ChatSpec>) =>
    request<ChatSpec>("/chats", {
      method: "POST",
      body: JSON.stringify(chat),
    }),

  getChat: (chatId: string, options?: { signal?: AbortSignal }) =>
    request<ChatHistory>(`/chats/${encodeURIComponent(chatId)}`, {
      signal: options?.signal,
    }),

  getChatStatus: (
    chatId: string,
    options?: { signal?: AbortSignal; agentId?: string },
  ) =>
    request<ChatStatusResponse>(
      `/chats/${encodeURIComponent(chatId)}/status`,
      {
        signal: options?.signal,
        headers: options?.agentId
          ? { "X-Agent-Id": options.agentId }
          : undefined,
      },
    ),

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

  archiveChat: (chatId: string) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}/archive`, {
      method: "POST",
    }),

  unarchiveChat: (chatId: string) =>
    request<ChatSpec>(`/chats/${encodeURIComponent(chatId)}/unarchive`, {
      method: "POST",
    }),

  batchArchiveChats: (chatIds: string[]) =>
    request<BatchArchiveResult>("/chats/actions/batch-archive", {
      method: "POST",
      body: JSON.stringify({ chat_ids: chatIds }),
    }),

  batchUnarchiveChats: (chatIds: string[]) =>
    request<BatchArchiveResult>("/chats/actions/batch-unarchive", {
      method: "POST",
      body: JSON.stringify({ chat_ids: chatIds }),
    }),

  stopChat: (chatId: string) =>
    request<void>(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
      method: "POST",
    }),

  listConversationMembers: (chatId: string) =>
    request<ConversationMember[]>(
      `/chats/${encodeURIComponent(chatId)}/members`,
    ),

  listConversationShareCandidates: (chatId: string) =>
    request<ConversationShareCandidate[]>(
      `/chats/${encodeURIComponent(chatId)}/share-candidates`,
    ),

  addConversationViewer: (chatId: string, userId: string) =>
    request<ConversationMember>(
      `/chats/${encodeURIComponent(chatId)}/members`,
      {
        method: "POST",
        body: JSON.stringify({ user_id: userId }),
      },
    ),

  removeConversationViewer: (chatId: string, userId: string) =>
    request<{ success: boolean; removed: boolean }>(
      `/chats/${encodeURIComponent(chatId)}/members/${encodeURIComponent(
        userId,
      )}`,
      { method: "DELETE" },
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

  getSession: (sessionId: string) =>
    request<ChatHistory>(`/chats/${encodeURIComponent(sessionId)}`),

  deleteSession: (sessionId: string) =>
    request<ChatDeleteResponse>(`/chats/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    }),

  createSession: (session: Partial<Session>) =>
    request<Session>("/chats", {
      method: "POST",
      body: JSON.stringify(session),
    }),

  updateSession: (sessionId: string, session: ChatUpdateRequest) =>
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
