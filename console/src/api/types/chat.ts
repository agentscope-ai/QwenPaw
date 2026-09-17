export type ChatStatus = "idle" | "running";

export interface ChatSpec {
  id: string; // Chat UUID identifier
  session_id: string; // Session identifier (channel:user_id format)
  user_id: string; // User identifier
  channel: string; // Channel name, default: "default"
  name?: string; // Chat display name
  created_at: string | null; // Chat creation timestamp (ISO 8601)
  updated_at: string | null; // Chat last update timestamp (ISO 8601)
  meta?: Record<string, unknown>; // Additional metadata
  status?: ChatStatus; // Conversation status: idle or running
  pinned?: boolean; // Whether the chat is pinned to the top
  archived_at?: string | null; // When the chat was archived (ISO 8601), null = active
  archived?: boolean; // Computed: whether the chat is archived
  access_role?: "owner" | "viewer";
  read_only?: boolean;
  shared_by?: string | null;
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  status?: ChatStatus; // Conversation status: idle or running
  access_role?: "owner" | "viewer";
  read_only?: boolean;
  shared_by?: string | null;
}

export function isConversationReadOnly(
  chat:
    | Pick<ChatSpec, "access_role" | "read_only">
    | Pick<ChatHistory, "access_role" | "read_only">
    | null
    | undefined,
): boolean {
  return chat?.read_only === true || chat?.access_role === "viewer";
}

export interface ChatUpdateRequest {
  name?: string;
  pinned?: boolean;
}

export interface ChatDeleteResponse {
  success: boolean;
  chat_id: string;
}

export interface ConversationMember {
  conversation_id: string;
  user_id: string;
  username: string;
  role: "viewer";
  granted_by: string;
  created_at: string;
}

export interface ConversationShareCandidate {
  user_id: string;
  username: string;
  platform_role: "admin" | "member";
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
