import { useCallback, useRef } from "react";
import { chatApi } from "@/api/modules/chat";
import { toStoredName } from "@/pages/Chat/utils";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore } from "../stores/sessionStore";
import type {
  ChatConfig,
  ChatInputData,
  ChatMessage,
  MessageContent,
  StreamResponse,
  StreamResponseMessage,
  StreamContentItem,
} from "../types";
import {
  MESSAGE_STATUS,
  ROLES,
  STORAGE_KEYS,
  DEFAULT_MAX_STREAM_RETRIES,
  DEFAULT_STREAM_RETRY_DELAY_MS,
} from "../constants";
import {
  STREAM_MESSAGE_TYPES,
  TOOL_INPUT_TYPES,
  TOOL_OUTPUT_TYPES,
} from "../types";

/** Convert a backend file/image URL to a displayable URL */
function toDisplayUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("data:")) return url;
  if (url.startsWith("file://")) url = url.replace("file://", "");
  return chatApi.filePreviewUrl(url.startsWith("/") ? url : `/${url}`);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

/**
 * Extract plain text from tool output.
 * Backend may return ToolResponse content in several shapes:
 *   - "plain string"
 *   - [{type:"text", text:"..."}, ...]
 *   - {text: "..."}
 *   - {content: [...]}                (MCP-style)
 *   - {output: <recursive>}            (nested wrapper)
 * Falls back to pretty JSON only if no text-like field is found.
 */
function normalizeToolOutput(output: unknown): string | undefined {
  if (output == null) return undefined;
  if (typeof output === "string") {
    // Try parsing JSON strings that look like arrays/objects
    const trimmed = output.trim();
    if (
      (trimmed.startsWith("[") && trimmed.endsWith("]")) ||
      (trimmed.startsWith("{") && trimmed.endsWith("}"))
    ) {
      try {
        const parsed = JSON.parse(trimmed);
        if (typeof parsed === "object" && parsed !== null) {
          const inner = normalizeToolOutput(parsed);
          if (inner !== undefined && inner !== trimmed) return inner;
        }
      } catch {
        // Not valid JSON, return as plain string
      }
    }
    return output;
  }
  if (Array.isArray(output)) {
    const texts = output
      .map((item: unknown) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const obj = item as Record<string, unknown>;
          if (typeof obj.text === "string") return obj.text;
          if (obj.content !== undefined)
            return normalizeToolOutput(obj.content) || "";
          if (obj.output !== undefined)
            return normalizeToolOutput(obj.output) || "";
        }
        return "";
      })
      .filter(Boolean);
    return texts.join("\n") || undefined;
  }
  if (typeof output === "object") {
    const obj = output as Record<string, unknown>;
    if (typeof obj.text === "string") return obj.text;
    if (obj.content !== undefined) {
      const inner = normalizeToolOutput(obj.content);
      if (inner !== undefined) return inner;
    }
    if (obj.output !== undefined) {
      const inner = normalizeToolOutput(obj.output);
      if (inner !== undefined) return inner;
    }
  }
  return JSON.stringify(output, null, 2);
}

/** Parse a single SSE line into a StreamResponse */
function parseStreamChunk(line: string): StreamResponse | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith(":")) return null;

  // Handle "data: ..." prefix (standard SSE)
  const data = trimmed.startsWith("data:") ? trimmed.slice(5).trim() : trimmed;

  if (data === "[DONE]") return null;

  try {
    return JSON.parse(data) as StreamResponse;
  } catch {
    return null;
  }
}

/** Normalize content items from array */
function normalizeContentItems(items: StreamContentItem[]): MessageContent[] {
  const result: MessageContent[] = [];
  for (const item of items) {
    switch (item.type) {
      case "text":
        result.push({ type: "text", text: item.text || "" });
        break;
      case "image":
        result.push({
          type: "image",
          url: toDisplayUrl((item.image_url as string) || ""),
          alt: item.alt as string | undefined,
        });
        break;
      case "video":
        result.push({
          type: "video",
          url: toDisplayUrl((item.video_url as string) || ""),
        });
        break;
      case "audio":
        result.push({
          type: "audio",
          url: toDisplayUrl((item.data as unknown as string) || ""),
        });
        break;
      case "file":
        result.push({
          type: "file",
          url: toDisplayUrl(
            (item.file_url as string) || (item.file_id as string) || "",
          ),
          name:
            (item.file_name as string) || (item.filename as string) || "file",
          size: item.size as number | undefined,
        });
        break;
      case "refusal":
        result.push({
          type: "text",
          text: (item.refusal as string) || (item.text as string) || "",
        });
        break;
      default:
        // data type or unknown — skip silently
        break;
    }
  }
  return result;
}

/** Convert backend message content to our MessageContent format */
function normalizeContent(content: unknown): MessageContent[] {
  if (typeof content === "string") {
    return [{ type: "text", text: content }];
  }
  if (!Array.isArray(content)) {
    return [{ type: "text", text: String(content || "") }];
  }
  return normalizeContentItems(content as StreamContentItem[]);
}

/**
 * Merge tool input+output messages by call_id/name.
 * After merge, each tool input message's content array includes both
 * the input content and the output content.
 */
function mergeToolMessages(
  messages: StreamResponseMessage[],
): StreamResponseMessage[] {
  const bufferMap = new Map<string, number>();
  const result: StreamResponseMessage[] = [];

  for (const msg of messages) {
    const type = msg.type || "";
    const contentArr = Array.isArray(msg.content)
      ? (msg.content as StreamContentItem[])
      : [];

    if (TOOL_INPUT_TYPES.has(type) && contentArr.length > 0) {
      const data = contentArr[0]?.data;
      const key =
        (data?.call_id as string) || (data?.name as string) || msg.id || "";
      bufferMap.set(key, result.length);
      result.push(msg);
    } else if (TOOL_OUTPUT_TYPES.has(type) && contentArr.length > 0) {
      const data = contentArr[0]?.data;
      const key = (data?.call_id as string) || (data?.name as string) || "";
      const inputIdx = bufferMap.get(key);
      if (inputIdx !== undefined) {
        const inputMsg = result[inputIdx];
        const inputContent = Array.isArray(inputMsg.content)
          ? (inputMsg.content as StreamContentItem[])
          : [];
        // Merge output into input message — preserve INPUT type so
        // responseToContent recognizes it as a tool call
        result[inputIdx] = {
          ...inputMsg,
          status: msg.status || inputMsg.status,
          content: [...inputContent, ...contentArr],
        };
      } else {
        result.push(msg);
      }
    } else {
      result.push(msg);
    }
  }
  return result;
}

/**
 * Convert a stream response's output messages to our MessageContent[].
 * Handles reasoning, tool calls, messages, and errors.
 */
function responseToContent(
  messages: StreamResponseMessage[],
): MessageContent[] {
  const merged = mergeToolMessages(messages);
  const result: MessageContent[] = [];

  for (const msg of merged) {
    const type = msg.type || STREAM_MESSAGE_TYPES.MESSAGE;

    switch (type) {
      case STREAM_MESSAGE_TYPES.REASONING: {
        // Reasoning/thinking block
        const contentArr = Array.isArray(msg.content)
          ? (msg.content as StreamContentItem[])
          : [];
        const text =
          contentArr
            .filter((c) => c.type === "text")
            .map((c) => c.text || "")
            .join("") || "";
        if (text || msg.status === "in_progress") {
          result.push({
            type: "thinking",
            text,
            collapsed: msg.status === "completed",
          });
        }
        break;
      }

      case STREAM_MESSAGE_TYPES.PLUGIN_CALL:
      case STREAM_MESSAGE_TYPES.FUNCTION_CALL:
      case STREAM_MESSAGE_TYPES.COMPONENT_CALL:
      case STREAM_MESSAGE_TYPES.MCP_CALL: {
        // Tool call (may include merged output)
        const contentArr = Array.isArray(msg.content)
          ? (msg.content as StreamContentItem[])
          : [];
        const inputData = contentArr[0]?.data;
        const outputData = contentArr[1]?.data;
        const name = (inputData?.name as string) || type;
        const serverLabel = inputData?.server_label as string | undefined;
        const callStatus =
          msg.status === "in_progress"
            ? "calling"
            : msg.status === "completed"
            ? "done"
            : outputData
            ? "done"
            : "calling";

        // Parse arguments — backend sends it as a JSON string
        let params: Record<string, unknown> = {};
        const rawArgs = inputData?.arguments;
        if (typeof rawArgs === "string" && rawArgs) {
          try {
            params = JSON.parse(rawArgs) as Record<string, unknown>;
          } catch {
            params = { _raw: rawArgs };
          }
        } else if (rawArgs && typeof rawArgs === "object") {
          params = rawArgs as Record<string, unknown>;
        }

        result.push({
          type: "tool_call",
          id: (inputData?.call_id as string) || msg.id || generateId(),
          name,
          serverLabel,
          params,
          result: normalizeToolOutput(outputData?.output),
          status: callStatus,
        });
        break;
      }

      case STREAM_MESSAGE_TYPES.MCP_APPROVAL_REQUEST: {
        // MCP approval request — render as tool_call with special name
        const contentArr = Array.isArray(msg.content)
          ? (msg.content as StreamContentItem[])
          : [];
        const data = contentArr[0]?.data;
        result.push({
          type: "tool_call",
          id: msg.id || generateId(),
          name: (data?.name as string) || "mcp_approval",
          serverLabel: data?.server_label as string | undefined,
          params: (data?.arguments as Record<string, unknown>) || {},
          status: "calling",
        });
        break;
      }

      case STREAM_MESSAGE_TYPES.ERROR: {
        // Error message
        const errorText = msg.message || "Unknown error";
        result.push({ type: "text", text: `Error: ${errorText}` });
        break;
      }

      case STREAM_MESSAGE_TYPES.HEARTBEAT:
        // Ignore heartbeats
        break;

      case STREAM_MESSAGE_TYPES.MESSAGE:
      default: {
        // Regular message — extract text/image/file content
        result.push(...normalizeContent(msg.content));
        break;
      }
    }
  }

  // Post-process: if a thinking block is followed by non-thinking content,
  // mark it as collapsed (thinking is done) even if backend didn't send
  // a completed status for the reasoning message.
  for (let i = 0; i < result.length; i++) {
    if (result[i].type === "thinking" && !(result[i] as any).collapsed) {
      const hasFollowingContent = result
        .slice(i + 1)
        .some((c) => c.type !== "thinking");
      if (hasFollowingContent) {
        (result[i] as any).collapsed = true;
      }
    }
  }

  return result;
}

/** Check if a response indicates history should be cleared */
function shouldClearHistory(response: StreamResponse): boolean {
  if (response.object === "message") {
    const meta = (response as unknown as Record<string, unknown>).metadata as
      | Record<string, unknown>
      | undefined;
    return (
      meta?.clear_history === true ||
      (meta?.metadata as Record<string, unknown>)?.clear_history === true
    );
  }
  if (response.object === "response" && Array.isArray(response.output)) {
    return response.output.some((msg) => {
      const meta = msg.metadata as Record<string, unknown> | undefined;
      return (
        meta?.clear_history === true ||
        (meta?.metadata as Record<string, unknown>)?.clear_history === true
      );
    });
  }
  return false;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseChatStreamOptions {
  config: ChatConfig;
  sessionId: string | null;
  onHistoryClear?: () => void;
  onError?: (error: Error) => void;
}

export interface UseChatStreamReturn {
  send: (input: ChatInputData) => Promise<void>;
  cancel: () => void;
  reconnect: () => Promise<void>;
  isStreaming: boolean;
}

/**
 * State for the ResponseBuilder — tracks messages by ID
 * so we can handle incremental content deltas.
 */
interface ResponseState {
  messages: Map<string, StreamResponseMessage>;
  orderedIds: string[];
  status: string;
}

function createResponseState(): ResponseState {
  return { messages: new Map(), orderedIds: [], status: "created" };
}

function applyResponseEvent(
  state: ResponseState,
  event: StreamResponse,
): ResponseState {
  const next: ResponseState = {
    messages: new Map(state.messages),
    orderedIds: [...state.orderedIds],
    status: state.status,
  };

  if (event.object === "response") {
    // Response events: update status, merge output messages by ID.
    // NEVER remove existing messages — they arrive via message/content events
    // and response.output may be partial (only changed messages).
    if (event.status) next.status = event.status;
    if (event.output && event.output.length > 0) {
      for (const msg of event.output) {
        const id = msg.id;
        if (!id) continue; // Skip messages without stable IDs
        const existing = next.messages.get(id);
        if (existing) {
          // Merge: update fields, preserve content if new is empty
          const merged = { ...existing, ...msg, id };
          if (
            !msg.content ||
            (Array.isArray(msg.content) && msg.content.length === 0)
          ) {
            merged.content = existing.content;
          }
          next.messages.set(id, merged);
        } else {
          next.orderedIds.push(id);
          next.messages.set(id, { ...msg, id });
        }
      }
    }
  } else if (event.object === "message") {
    // Single message update
    const id = (event as unknown as { id: string }).id || generateId();
    const type = event.type || STREAM_MESSAGE_TYPES.MESSAGE;
    if (type === STREAM_MESSAGE_TYPES.HEARTBEAT) return state;

    const existing = next.messages.get(id);
    if (existing) {
      // Update existing message, preserve content if new event has empty
      const newContent = event.content;
      const merged = {
        ...existing,
        ...(event as unknown as StreamResponseMessage),
        id,
      };
      if (
        !newContent ||
        (Array.isArray(newContent) && newContent.length === 0)
      ) {
        merged.content = existing.content;
      }
      next.messages.set(id, merged);
    } else {
      next.orderedIds.push(id);
      next.messages.set(id, {
        ...(event as unknown as StreamResponseMessage),
        id,
      });
    }
  } else if (event.object === "content") {
    // Content delta — append to a specific message
    const msgId =
      event.msg_id || (event as unknown as { msg_id: string }).msg_id;
    const msg = next.messages.get(msgId);
    if (msg) {
      const contentArr = Array.isArray(msg.content)
        ? ([...msg.content] as StreamContentItem[])
        : [];

      if (event.delta) {
        // Delta: merge into last content item if compatible
        const last = contentArr[contentArr.length - 1];
        const eventType = event.type || "text";

        if (last?.delta && last.type === eventType) {
          // Same type as last delta item — merge in place
          if (eventType === "text") {
            contentArr[contentArr.length - 1] = {
              ...last,
              text: (last.text || "") + (event.text || ""),
            };
          } else if (eventType === "data") {
            // Data delta: replace data (matches Builder behavior)
            contentArr[contentArr.length - 1] = {
              ...last,
              data: event.data as Record<string, unknown> | undefined,
            };
          } else if (eventType === "image") {
            contentArr[contentArr.length - 1] = {
              ...last,
              image_url: event.image_url as string | undefined,
            };
          } else {
            // Other types: replace the content item
            contentArr[contentArr.length - 1] = {
              ...last,
              ...event,
              delta: true,
            } as StreamContentItem;
          }
        } else {
          // New delta item
          contentArr.push({
            type: eventType,
            text: event.text,
            image_url: event.image_url as string | undefined,
            data: event.data as Record<string, unknown> | undefined,
            delta: true,
          } as StreamContentItem);
        }
      } else {
        // Full content replace
        if (contentArr.length > 0) {
          Object.assign(contentArr[contentArr.length - 1], event);
        } else {
          contentArr.push(event as unknown as StreamContentItem);
        }
      }

      next.messages.set(msgId, { ...msg, content: contentArr });
    }
  }

  return next;
}

function stateToMessages(state: ResponseState): StreamResponseMessage[] {
  return state.orderedIds
    .map((id) => state.messages.get(id))
    .filter(Boolean) as StreamResponseMessage[];
}

// ---------------------------------------------------------------------------
// Streaming session persistence helpers (page-refresh recovery)
// ---------------------------------------------------------------------------

interface StreamingSessionInfo {
  sessionId: string;
  timestamp: number;
}

function saveStreamingSession(sessionId: string): void {
  try {
    sessionStorage.setItem(
      STORAGE_KEYS.STREAMING_SESSION_KEY,
      JSON.stringify({
        sessionId,
        timestamp: Date.now(),
      } as StreamingSessionInfo),
    );
  } catch {
    // Ignore storage errors
  }
}

function clearStreamingSession(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEYS.STREAMING_SESSION_KEY);
  } catch {
    // Ignore
  }
}

/**
 * Save pending user message so it can be restored after page refresh.
 * The backend may not yet have persisted it when the history is reloaded.
 */
function savePendingUserMessage(sessionId: string, msg: ChatMessage): void {
  try {
    localStorage.setItem(
      STORAGE_KEYS.PENDING_USER_MSG_PREFIX + sessionId,
      JSON.stringify(msg),
    );
  } catch {
    // Ignore
  }
}

function loadPendingUserMessage(sessionId: string): ChatMessage | null {
  try {
    const raw = localStorage.getItem(
      STORAGE_KEYS.PENDING_USER_MSG_PREFIX + sessionId,
    );
    if (!raw) return null;
    return JSON.parse(raw) as ChatMessage;
  } catch {
    return null;
  }
}

function clearPendingUserMessage(sessionId: string): void {
  try {
    localStorage.removeItem(STORAGE_KEYS.PENDING_USER_MSG_PREFIX + sessionId);
  } catch {
    // Ignore
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useChatStream({
  config,
  sessionId,
  onHistoryClear,
  onError,
}: UseChatStreamOptions): UseChatStreamReturn {
  const abortRef = useRef<AbortController | null>(null);
  const store = useChatStore;
  const sessionStore = useSessionStore;

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    clearStreamingSession();

    const state = store.getState();
    if (state.streamingMessageId && sessionId) {
      store.getState().updateMessage(sessionId, state.streamingMessageId, {
        status: MESSAGE_STATUS.CANCELLED,
      });
      store.getState().setStreamingMessage(null);
      store.getState().setGenerating(false);
    }

    // Also notify backend to stop
    if (sessionId && config.apiEndpoint) {
      fetch(
        `${config.apiEndpoint}/stop?chat_id=${encodeURIComponent(sessionId)}`,
        {
          method: "POST",
          headers: config.headers,
        },
      ).catch(() => {});
    }
  }, [sessionId, config, store]);

  /**
   * Issue a reconnect request to the backend.
   * Shared by both manual reconnect and auto-retry logic.
   */
  const fetchReconnect = useCallback(
    (targetSessionId: string, signal: AbortSignal): Promise<Response> => {
      const session = sessionStore
        .getState()
        .sessions.find((s) => s.id === targetSessionId);
      const streamSessionId = session?.sessionId || targetSessionId;

      return fetch(config.apiEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...config.headers,
        },
        body: JSON.stringify({
          reconnect: true,
          session_id: streamSessionId,
          user_id: config.userId || "default",
          channel: config.channel || "console",
        }),
        signal,
      });
    },
    [config, sessionStore],
  );

  // Refs to hold mutable config/callbacks so processStream can stay stable
  const configRef = useRef(config);
  configRef.current = config;
  const fetchReconnectRef = useRef(fetchReconnect);
  fetchReconnectRef.current = fetchReconnect;

  const processStream = useCallback(
    async (
      response: Response,
      assistantMsgId: string,
      targetSessionId: string,
    ) => {
      const reader = response.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";
      let pendingClearHistory = false;
      let responseState = createResponseState();

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const parsed = parseStreamChunk(line);
            if (!parsed) continue;

            // Check for history clear signal
            if (shouldClearHistory(parsed)) {
              pendingClearHistory = true;
            }

            // Apply event to response state
            responseState = applyResponseEvent(responseState, parsed);

            // Convert accumulated state to content
            const messages = stateToMessages(responseState);
            const content = responseToContent(messages);
            store
              .getState()
              .updateStreamContent(targetSessionId, assistantMsgId, content);

            // Check completion
            if (responseState.status === "completed") {
              clearStreamingSession();
              clearPendingUserMessage(targetSessionId);
              store
                .getState()
                .finalizeMessage(targetSessionId, assistantMsgId, {
                  usage: parsed.usage,
                });

              if (pendingClearHistory) {
                onHistoryClear?.();
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") return;

        // Network error — attempt auto-reconnect before giving up
        if (configRef.current.enableReconnect) {
          const recovered = await autoReconnectRef.current(
            assistantMsgId,
            targetSessionId,
          );
          // If recovered, the new processStream call handles its own cleanup.
          // Do NOT reset generating state here.
          if (recovered) return;
        }

        store.getState().updateMessage(targetSessionId, assistantMsgId, {
          status: MESSAGE_STATUS.ERROR,
        });
        clearStreamingSession();
        onError?.(err as Error);
        // Fall through to finally for state cleanup
      } finally {
        // Only reset if we're still the active streaming message
        // (autoReconnect may have already started a new stream)
        const currentState = store.getState();
        if (currentState.streamingMessageId === assistantMsgId) {
          store.getState().setGenerating(false);
          store.getState().setStreamingMessage(null);
        }
      }
    },
    // Keep deps minimal and stable — mutable values accessed via refs
    [store, onHistoryClear, onError],
  );

  // Ref-based auto-reconnect to avoid stale closure in processStream's catch.
  // processStream captures autoReconnectRef instead of a bare function, so it
  // always calls the latest version without needing it in its deps array.
  const autoReconnectRef = useRef<
    (msgId: string, sid: string) => Promise<boolean>
  >(async () => false);

  autoReconnectRef.current = async (
    assistantMsgId: string,
    targetSessionId: string,
  ): Promise<boolean> => {
    const currentMaxRetries =
      configRef.current.maxStreamRetries ?? DEFAULT_MAX_STREAM_RETRIES;
    const currentRetryDelay =
      configRef.current.streamRetryDelayMs ?? DEFAULT_STREAM_RETRY_DELAY_MS;

    for (let attempt = 0; attempt < currentMaxRetries; attempt++) {
      const delay = currentRetryDelay * Math.pow(2, attempt);
      console.warn(
        `[useChatStream] SSE disconnected. Retry ${
          attempt + 1
        }/${currentMaxRetries} in ${delay}ms`,
      );
      await new Promise((resolve) => setTimeout(resolve, delay));

      if (!abortRef.current || abortRef.current.signal.aborted) return false;

      try {
        const abortController = new AbortController();
        abortRef.current = abortController;

        const reconnectResponse = await fetchReconnectRef.current(
          targetSessionId,
          abortController.signal,
        );

        if (!reconnectResponse.ok) {
          throw new Error(`Reconnect failed: ${reconnectResponse.status}`);
        }

        // Re-enter stream processing with the new response.
        // Reset generating state since processStream's finally will set it again.
        store.getState().setStreamingMessage(assistantMsgId);
        store.getState().setGenerating(true);
        await processStream(reconnectResponse, assistantMsgId, targetSessionId);
        return true;
      } catch (err) {
        if ((err as Error).name === "AbortError") return false;
        console.warn(
          `[useChatStream] Retry ${attempt + 1}/${currentMaxRetries} failed:`,
          err,
        );
      }
    }
    return false;
  };

  const send = useCallback(
    async (input: ChatInputData) => {
      // If no active session, create one first (seamlessly)
      let currentSessionId = sessionId;
      if (!currentSessionId) {
        const id = await sessionStore
          .getState()
          .createSession(
            config.userId || "default",
            config.channel || "console",
          );
        store.getState().setActiveSession(id);
        currentSessionId = id;
      }

      // Create user message
      const userMsg: ChatMessage = {
        id: generateId(),
        role: "user",
        content: [{ type: "text", text: input.text }],
        status: MESSAGE_STATUS.COMPLETED,
        createdAt: Date.now(),
      };

      // Add file contents if present
      if (input.files?.length) {
        for (const file of input.files) {
          if (file.url || file.response?.url) {
            const url = file.url || file.response?.url || "";
            const isImage = file.type?.startsWith("image/");
            if (isImage) {
              userMsg.content.push({ type: "image", url });
            } else {
              userMsg.content.push({
                type: "file",
                url,
                name: file.name,
                size: file.size,
              });
            }
          }
        }
      }

      store.getState().addMessage(currentSessionId, userMsg);

      // Persist user message for page-refresh recovery
      savePendingUserMessage(currentSessionId, userMsg);

      // Create placeholder assistant message
      const assistantMsgId = generateId();
      const assistantMsg: ChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: [],
        status: MESSAGE_STATUS.STREAMING,
        createdAt: Date.now(),
      };
      store.getState().addMessage(currentSessionId, assistantMsg);
      store.getState().setStreamingMessage(assistantMsgId);
      store.getState().setGenerating(true);

      // Persist streaming state for page-refresh recovery
      saveStreamingSession(currentSessionId);

      // Update session
      sessionStore.getState().updateSessionStatus(currentSessionId, "running");
      sessionStore
        .getState()
        .updateSessionLastMessage(currentSessionId, input.text.slice(0, 100));

      // Build request
      const abortController = new AbortController();
      abortRef.current = abortController;

      // Resolve session_id (timestamp) from the session object
      const currentSession = sessionStore
        .getState()
        .sessions.find((s) => s.id === currentSessionId);
      const streamSessionId = currentSession?.sessionId || currentSessionId;

      const requestBody = {
        input: [
          {
            role: ROLES.USER,
            content: userMsg.content.map((c) => {
              if (c.type === "text") return { type: "text", text: c.text };
              if (c.type === "image")
                return { type: "image", image_url: toStoredName(c.url) };
              if (c.type === "file")
                return {
                  type: "file",
                  file_url: toStoredName(c.url),
                  file_name: c.name,
                };
              return c;
            }),
          },
        ],
        session_id: streamSessionId,
        user_id: config.userId || "default",
        channel: config.channel || "console",
        stream: true,
        ...input.bizParams,
      };

      try {
        const response = await fetch(config.apiEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...config.headers,
          },
          body: JSON.stringify(requestBody),
          signal: abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`Chat request failed: ${response.status}`);
        }

        await processStream(response, assistantMsgId, currentSessionId);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        store.getState().updateMessage(currentSessionId, assistantMsgId, {
          status: MESSAGE_STATUS.ERROR,
        });
        store.getState().setGenerating(false);
        store.getState().setStreamingMessage(null);
        clearStreamingSession();
        onError?.(err as Error);
      } finally {
        sessionStore.getState().updateSessionStatus(currentSessionId, "idle");
      }
    },
    [sessionId, config, store, sessionStore, processStream, onError],
  );

  const reconnect = useCallback(async () => {
    if (!sessionId || !config.enableReconnect) return;

    // Restore pending user message if it's missing from the loaded history
    // (backend may not have persisted it yet when history was fetched)
    const pendingUserMsg = loadPendingUserMessage(sessionId);
    if (pendingUserMsg) {
      const existingMessages = store.getState().getMessages(sessionId) || [];
      const alreadyExists = existingMessages.some(
        (m) => m.id === pendingUserMsg.id,
      );
      if (!alreadyExists) {
        store.getState().addMessage(sessionId, pendingUserMsg);
      }
    }

    const assistantMsgId = generateId();
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: [],
      status: MESSAGE_STATUS.STREAMING,
      createdAt: Date.now(),
    };
    store.getState().addMessage(sessionId, assistantMsg);
    store.getState().setStreamingMessage(assistantMsgId);
    store.getState().setGenerating(true);

    // Persist streaming state for page-refresh recovery
    saveStreamingSession(sessionId);

    const abortController = new AbortController();
    abortRef.current = abortController;

    try {
      const response = await fetchReconnect(sessionId, abortController.signal);

      if (!response.ok) {
        throw new Error(`Reconnect failed: ${response.status}`);
      }

      await processStream(response, assistantMsgId, sessionId);

      // If stream completed but message is still empty (no content received),
      // treat as idle: remove placeholder and reset state
      const msg = store
        .getState()
        .getMessages(sessionId)
        ?.find((m) => m.id === assistantMsgId);
      if (msg && msg.content.length === 0) {
        store.getState().removeMessage(sessionId, assistantMsgId);
        store.getState().setGenerating(false);
        store.getState().setStreamingMessage(null);
        clearStreamingSession();
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      store.getState().removeMessage(sessionId, assistantMsgId);
      store.getState().setGenerating(false);
      store.getState().setStreamingMessage(null);
      clearStreamingSession();
      clearPendingUserMessage(sessionId);
    } finally {
      sessionStore.getState().updateSessionStatus(sessionId, "idle");
    }
  }, [sessionId, config, store, sessionStore, processStream, fetchReconnect]);

  // Page-refresh/reopen recovery is handled by ChatContainer which watches
  // the backend session status (SESSION_STATUS.RUNNING) and calls reconnect().
  // No sessionStorage-based recovery needed here — this ensures close-then-
  // reopen also works (sessionStorage is cleared on tab close).

  const isStreaming = useChatStore((s) => s.isGenerating);

  return { send, cancel, reconnect, isStreaming };
}
