export type ChatStatus = "idle" | "running";

export interface ChatSpec {
  id: string; // Chat UUID identifier
  name?: string; // Chat display name
  session_id: string; // Session identifier (channel:user_id format)
  user_id: string; // User identifier
  channel: string; // Channel name, default: "default"
  created_at: string | null; // Chat creation timestamp (ISO 8601)
  updated_at: string | null; // Chat last update timestamp (ISO 8601)
  meta?: Record<string, unknown>; // Additional metadata
  status?: ChatStatus; // Conversation status: idle or running
}

export interface Message {
  role: string;
  content: unknown;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: Message[];
  status?: ChatStatus; // Conversation status: idle or running
  has_more?: boolean;
  total?: number;
}

export interface ChatRuntimeStatusBreakdownItem {
  key: string;
  label: string;
  tokens: number;
  ratio: number;
  section: "system" | "user";
}

export interface ChatRuntimeStatus {
  scope_level: string;
  snapshot_source: string;
  snapshot_stage: string;
  agent_id?: string | null;
  session_id?: string | null;
  user_id?: string | null;
  chat_id?: string | null;
  context_window_tokens: number;
  used_tokens: number;
  used_ratio: number;
  reserved_response_tokens: number;
  remaining_tokens: number;
  model_id?: string | null;
  provider_id?: string | null;
  profile_label: string;
  breakdown: ChatRuntimeStatusBreakdownItem[];
}

export interface ChatDeleteResponse {
  success: boolean;
  chat_id: string;
}

// Legacy Session type alias for backward compatibility
export type Session = ChatSpec;
