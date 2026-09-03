export type ChatStatus = "idle" | "running";
export type ChatSource = "chat" | "cron" | "subagent";
export type ChatGroupKind = "default" | "cron" | "subagents" | "custom";

export interface ChatGroup {
  id: string;
  name: string;
  order: number;
  kind: ChatGroupKind;
  source?: ChatSource | null;
  pinned: boolean;
}

export interface ChatSpec {
  id: string; // Chat UUID identifier
  session_id: string; // Session identifier (channel:user_id format)
  user_id: string; // User identifier
  channel: string; // Channel name, default: "default"
  name?: string; // Chat display name
  created_at: string | null; // Chat creation timestamp (ISO 8601)
  updated_at: string | null; // Chat last update timestamp (ISO 8601)
  last_finished_at?: string | null; // Most recent task completion timestamp
  meta?: Record<string, unknown>; // Additional metadata
  status?: ChatStatus; // Conversation status: idle or running
  pinned?: boolean; // Whether the chat is pinned to the top
  archived_at?: string | null; // When the chat was archived (ISO 8601), null = active
  archived?: boolean; // Computed: whether the chat is archived
  source?: ChatSource;
  group_id?: string | null;
  parent_session_id?: string | null;
  root_session_id?: string | null;
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  status?: ChatStatus; // Conversation status: idle or running
}

// Value semantics for GET /chats/{id}/messages — see
// docs/session-scroll-loading-design.md §2.1.
// - "available": more history exists before next_cursor; keep paging.
// - "complete": reached the true start of the conversation.
// - "expired": the true start was purged by an old retention policy.
// - "unavailable": this session has no history store to scroll into
//   (non-scroll mode) — messages is a capped safety window, not a page.
// - "degraded": history.db exists but couldn't be read for this request —
//   never treat this the same as "complete".
export type ChatHistoryStatus =
  | "available"
  | "complete"
  | "expired"
  | "unavailable"
  | "degraded";

export interface ChatMessagesPage {
  messages: Message[];
  next_cursor: number | null; // pass as before_seq to fetch the next (older) page
  has_more: boolean;
  history_status: ChatHistoryStatus;
  status: ChatStatus;
  truncated: boolean; // a single turn exceeded the expansion budget; next_cursor continues it
  fallback_limited: boolean; // messages is a capped safety window, not a normal page
}

export interface ChatUpdateRequest {
  name?: string;
  pinned?: boolean;
  group_id?: string;
}

export interface ChatDeleteResponse {
  success: boolean;
  chat_id: string;
}

export interface BatchArchiveResult {
  succeeded: string[];
  failed: Array<{
    chat_id: string;
    reason: "not_found" | "in_progress";
    message: string;
  }>;
}

// Legacy Session type alias for backward compatibility
export type Session = ChatSpec;
