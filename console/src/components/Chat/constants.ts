export const DEFAULT_USER_ID = "default";
export const DEFAULT_CHANNEL = "console";
export const DEFAULT_SESSION_NAME = "New Chat";
export const MAX_ATTACHMENT_SIZE_MB = 10;

export const ROLES = {
  USER: "user",
  ASSISTANT: "assistant",
  SYSTEM: "system",
  TOOL: "tool",
} as const;

export const MESSAGE_STATUS = {
  PENDING: "pending",
  STREAMING: "streaming",
  COMPLETED: "completed",
  ERROR: "error",
  CANCELLED: "cancelled",
} as const;

export const SESSION_STATUS = {
  IDLE: "idle",
  RUNNING: "running",
} as const;

export const STORAGE_KEYS = {
  PENDING_USER_MSG_PREFIX: "qwenpaw_pending_user_msg_",
  STREAMING_SESSION_KEY: "qwenpaw_streaming_session",
} as const;

/** Default max auto-reconnect attempts when SSE stream disconnects */
export const DEFAULT_MAX_STREAM_RETRIES = 3;
/** Default base delay (ms) between reconnect attempts (exponential backoff) */
export const DEFAULT_STREAM_RETRY_DELAY_MS = 1000;
