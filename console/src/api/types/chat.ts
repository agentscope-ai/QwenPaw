import type { ChatSpec as SharedChatSpec } from "@qwenpaw/api-contract";

export type {
  ChatGroup,
  ChatGroupKind,
  ChatSource,
  ChatStatus,
} from "@qwenpaw/api-contract";

export interface ChatSpec extends SharedChatSpec {
  created_at: string | null;
  updated_at: string | null;
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  status?: import("@qwenpaw/api-contract").ChatStatus;
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
