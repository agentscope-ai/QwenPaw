import type { UploadFile } from "antd";

// ---------------------------------------------------------------------------
// Message Types
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "assistant" | "system" | "tool";

export type MessageStatus =
  | "pending"
  | "streaming"
  | "completed"
  | "error"
  | "cancelled";

export interface TextContent {
  type: "text";
  text: string;
}

export interface ImageContent {
  type: "image";
  url: string;
  alt?: string;
}

export interface VideoContent {
  type: "video";
  url: string;
}

export interface AudioContent {
  type: "audio";
  url: string;
}

export interface FileContent {
  type: "file";
  url: string;
  name: string;
  size?: number;
}

export interface ThinkingContent {
  type: "thinking";
  text: string;
  collapsed?: boolean;
}

export type ToolCallStatus = "calling" | "done" | "error";

export interface ToolCallContent {
  type: "tool_call";
  id: string;
  name: string;
  serverLabel?: string;
  params: Record<string, unknown>;
  result?: unknown;
  status: ToolCallStatus;
}

export interface CardContent {
  type: "card";
  cardType: string;
  data: Record<string, unknown>;
}

export type MessageContent =
  | TextContent
  | ImageContent
  | VideoContent
  | AudioContent
  | FileContent
  | ThinkingContent
  | ToolCallContent
  | CardContent;

export interface MessageMetadata {
  model?: string;
  usage?: { prompt_tokens: number; completion_tokens: number };
  duration?: number;
  agentId?: string;
  sequenceNumber?: number;
  clearHistory?: boolean;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: MessageContent[];
  status: MessageStatus;
  metadata?: MessageMetadata;
  parentId?: string;
  createdAt: number;
}

// ---------------------------------------------------------------------------
// Session Types
// ---------------------------------------------------------------------------

export type SessionStatus = "idle" | "running";

export interface ChatSession {
  id: string;
  sessionId: string;
  userId: string;
  name: string;
  pinned: boolean;
  status: SessionStatus;
  createdAt: string;
  updatedAt: string;
  lastMessage?: string;
  /** Channel key (e.g. console, dingtalk) for display in session list */
  channel?: string;
}

export interface SessionGroup {
  label: string;
  sessions: ChatSession[];
}

// ---------------------------------------------------------------------------
// Input Types
// ---------------------------------------------------------------------------

export interface ChatInputData {
  text: string;
  files?: UploadFile[];
  bizParams?: Record<string, unknown>;
}

export interface CommandSuggestion {
  command: string;
  value: string;
  description: string;
  icon?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export interface ChatConfig {
  apiEndpoint: string;
  headers?: Record<string, string>;
  enableStream: boolean;
  enableReconnect: boolean;
  maxAttachmentSize: number;
  supportedMediaTypes: string[];
  userId?: string;
  channel?: string;
  /** Max auto-reconnect attempts when SSE stream disconnects unexpectedly */
  maxStreamRetries?: number;
  /** Base delay in ms between reconnect attempts (exponential backoff) */
  streamRetryDelayMs?: number;
}

// ---------------------------------------------------------------------------
// Tool Card Types
// ---------------------------------------------------------------------------

export interface ToolCardProps<T = Record<string, unknown>> {
  data: T;
  status: ToolCallStatus;
  toolName: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ToolCardComponent = React.FC<ToolCardProps<any>>;

export type ToolCardRegistry = Record<string, ToolCardComponent>;

// ---------------------------------------------------------------------------
// Stream Protocol Types (AgentScope Runtime compatible)
// ---------------------------------------------------------------------------

/**
 * AgentScope Runtime message types.
 * These correspond to the `type` field on messages in the stream.
 */
export const STREAM_MESSAGE_TYPES = {
  MESSAGE: "message",
  REASONING: "reasoning",
  PLUGIN_CALL: "plugin_call",
  PLUGIN_CALL_OUTPUT: "plugin_call_output",
  FUNCTION_CALL: "function_call",
  FUNCTION_CALL_OUTPUT: "function_call_output",
  COMPONENT_CALL: "component_call",
  COMPONENT_CALL_OUTPUT: "component_call_output",
  MCP_CALL: "mcp_call",
  MCP_CALL_OUTPUT: "mcp_call_output",
  MCP_APPROVAL_REQUEST: "mcp_approval_request",
  MCP_APPROVAL_RESPONSE: "mcp_approval_response",
  MCP_LIST_TOOLS: "mcp_list_tools",
  HEARTBEAT: "heartbeat",
  ERROR: "error",
} as const;

/** Tool input message types */
export const TOOL_INPUT_TYPES: Set<string> = new Set([
  STREAM_MESSAGE_TYPES.PLUGIN_CALL,
  STREAM_MESSAGE_TYPES.FUNCTION_CALL,
  STREAM_MESSAGE_TYPES.COMPONENT_CALL,
  STREAM_MESSAGE_TYPES.MCP_CALL,
]);

/** Tool output message types */
export const TOOL_OUTPUT_TYPES: Set<string> = new Set([
  STREAM_MESSAGE_TYPES.PLUGIN_CALL_OUTPUT,
  STREAM_MESSAGE_TYPES.FUNCTION_CALL_OUTPUT,
  STREAM_MESSAGE_TYPES.COMPONENT_CALL_OUTPUT,
  STREAM_MESSAGE_TYPES.MCP_CALL_OUTPUT,
]);

/** A content item within a stream message's content array */
export interface StreamContentItem {
  type: string;
  text?: string;
  data?: Record<string, unknown>;
  image_url?: string;
  video_url?: string;
  file_url?: string;
  file_id?: string;
  file_name?: string;
  filename?: string;
  size?: number;
  delta?: boolean;
  status?: string;
  [key: string]: unknown;
}

export interface StreamResponseMessage {
  id?: string;
  role: string;
  type?: string;
  status?: string;
  content: StreamContentItem[] | string | unknown;
  metadata?: Record<string, unknown>;
  sequence_number?: number;
  code?: string;
  message?: string;
}

/** SSE content delta event (object: "content") */
export interface StreamContentDelta {
  object: "content";
  msg_id: string;
  type: string;
  text?: string;
  image_url?: string;
  data?: unknown;
  delta?: boolean;
}

export interface StreamResponse {
  id?: string;
  object: "response" | "message" | "content";
  status?: "completed" | "in_progress" | "failed" | "created" | "canceled";
  output?: StreamResponseMessage[];
  created_at?: number;
  completed_at?: number;
  usage?: { prompt_tokens: number; completion_tokens: number };
  error?: unknown;
  // Fields for object: "message"
  type?: string;
  role?: string;
  content?: StreamContentItem[] | string | unknown;
  msg_id?: string;
  // Fields for object: "content"
  text?: string;
  delta?: boolean;
  image_url?: string;
  data?: Record<string, unknown>;
}
