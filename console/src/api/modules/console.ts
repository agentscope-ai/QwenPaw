import { request } from "../request";
import type {
  InboxEvent,
  PendingApproval,
  PushMessage,
  PushMessagesResponse,
} from "@qwenpaw/api-contract";

export type { InboxEvent, PendingApproval, PushMessage };

export interface InboxTrace {
  run_id: string;
  created_at: number;
  completed_at: number | null;
  status: string;
  meta: Record<string, unknown>;
  events: Array<{
    at: number;
    event: Record<string, unknown>;
  }>;
  error?: string;
}

export const consoleApi = {
  getPushMessages: (sessionId?: string) =>
    request<PushMessagesResponse>(
      sessionId
        ? `/console/push-messages?session_id=${sessionId}`
        : "/console/push-messages",
    ),

  getInboxEvents: (params?: {
    limit?: number;
    offset?: number;
    source_type?: string;
    source_types?: string[];
    status?: string;
    agent_id?: string;
    unread_only?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    if (params?.offset !== undefined)
      query.set("offset", String(params.offset));
    if (params?.source_type) query.set("source_type", params.source_type);
    for (const sourceType of params?.source_types ?? []) {
      query.append("source_types", sourceType);
    }
    if (params?.status) query.set("status", params.status);
    if (params?.agent_id) query.set("agent_id", params.agent_id);
    if (params?.unread_only !== undefined) {
      query.set("unread_only", String(params.unread_only));
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{
      events: InboxEvent[];
      total?: number;
      unread_count?: number;
    }>(`/console/inbox/events${suffix}`);
  },

  markInboxRead: (payload: { event_ids?: string[]; all?: boolean }) =>
    request<{ updated: number }>("/console/inbox/read", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteInboxEvent: (eventId: string) =>
    request<{
      deleted: boolean;
      trace_deleted?: boolean;
      run_id?: string | null;
    }>(`/console/inbox/events/${encodeURIComponent(eventId)}`, {
      method: "DELETE",
    }),

  getInboxTrace: (runId: string) =>
    request<InboxTrace>(`/console/inbox/traces/${encodeURIComponent(runId)}`),
};
