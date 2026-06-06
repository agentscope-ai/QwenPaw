import { useCallback, useEffect, useMemo } from "react";
import { useChatStore } from "../stores/chatStore";
import { chatApi } from "../../../api/modules/chat";
import type { ChatMessage, MessageContent, StreamContentItem } from "../types";
import {
  STREAM_MESSAGE_TYPES,
  TOOL_INPUT_TYPES,
  TOOL_OUTPUT_TYPES,
} from "../types";
import { MESSAGE_STATUS, ROLES } from "../constants";

const EMPTY_MESSAGES: ChatMessage[] = [];

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
      .map((item) => {
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

/** Extract plain text from MessageContent array */
export function extractText(content: MessageContent[]): string {
  return content
    .filter((c) => c.type === "text")
    .map((c) => (c as { type: "text"; text: string }).text)
    .join("\n");
}

/** Convert content items from backend array */
function convertContentItems(
  items: Array<Record<string, unknown>>,
): MessageContent[] {
  const result: MessageContent[] = [];
  for (const item of items) {
    switch (item.type) {
      case "text":
        result.push({ type: "text", text: (item.text as string) || "" });
        break;
      case "image":
        result.push({
          type: "image",
          url: toDisplayUrl((item.image_url as string) || ""),
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
          url: toDisplayUrl((item.data as string) || ""),
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
      default:
        break;
    }
  }
  return result;
}

/** Convert backend message format to ChatMessage, handling type field */
function convertBackendMessage(msg: Record<string, unknown>): ChatMessage {
  const role = msg.role as string;
  const content = msg.content;
  const msgType = (msg.type as string) || STREAM_MESSAGE_TYPES.MESSAGE;

  const messageContent: MessageContent[] = [];

  // Handle by message type
  if (msgType === STREAM_MESSAGE_TYPES.REASONING) {
    // Reasoning/thinking block
    const items = Array.isArray(content)
      ? (content as StreamContentItem[])
      : [];
    const text = items
      .filter((c) => c.type === "text")
      .map((c) => c.text || "")
      .join("");
    messageContent.push({ type: "thinking", text });
  } else if (TOOL_INPUT_TYPES.has(msgType)) {
    // Tool call
    const items = Array.isArray(content)
      ? (content as StreamContentItem[])
      : [];
    const inputData = items[0]?.data;
    const outputData = items[1]?.data;
    // Parse arguments — backend sends it as a JSON string
    let toolParams: Record<string, unknown> = {};
    const rawArgs = inputData?.arguments;
    if (typeof rawArgs === "string" && rawArgs) {
      try {
        toolParams = JSON.parse(rawArgs) as Record<string, unknown>;
      } catch {
        toolParams = { _raw: rawArgs };
      }
    } else if (rawArgs && typeof rawArgs === "object") {
      toolParams = rawArgs as Record<string, unknown>;
    }

    messageContent.push({
      type: "tool_call",
      id: (inputData?.call_id as string) || (msg.id as string) || generateId(),
      name: (inputData?.name as string) || msgType,
      serverLabel: inputData?.server_label as string | undefined,
      params: toolParams,
      result: normalizeToolOutput(outputData?.output),
      status: outputData ? "done" : "calling",
    });
  } else if (TOOL_OUTPUT_TYPES.has(msgType)) {
    // Standalone tool output (not merged) — render as result text
    const items = Array.isArray(content)
      ? (content as StreamContentItem[])
      : [];
    const outputData = items[0]?.data;
    if (outputData?.output != null) {
      const text = normalizeToolOutput(outputData.output);
      if (text) {
        messageContent.push({ type: "text", text });
      }
    }
  } else {
    // Regular message
    if (typeof content === "string") {
      messageContent.push({ type: "text", text: content });
    } else if (Array.isArray(content)) {
      messageContent.push(
        ...convertContentItems(content as Array<Record<string, unknown>>),
      );
    }
  }

  return {
    id: (msg.id as string) || generateId(),
    role: role === "user" ? "user" : role === "tool" ? "tool" : "assistant",
    content: messageContent,
    status: MESSAGE_STATUS.COMPLETED,
    metadata: {
      sequenceNumber: msg.sequence_number as number | undefined,
    },
    createdAt: Date.now(),
  };
}

/**
 * Merge tool input+output messages by call_id for history.
 * Tool output messages get folded into their corresponding input message.
 */
function mergeHistoryToolMessages(
  messages: Record<string, unknown>[],
): Record<string, unknown>[] {
  const bufferMap = new Map<string, number>();
  const result: Record<string, unknown>[] = [];

  for (const msg of messages) {
    const type = (msg.type as string) || "";
    const contentArr = Array.isArray(msg.content)
      ? (msg.content as StreamContentItem[])
      : [];

    if (TOOL_INPUT_TYPES.has(type) && contentArr.length > 0) {
      const data = contentArr[0]?.data;
      const key =
        (data?.call_id as string) ||
        (data?.name as string) ||
        (msg.id as string) ||
        "";
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
        result[inputIdx] = {
          ...msg,
          type: inputMsg.type as string,
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

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseChatMessagesOptions {
  sessionId: string | null;
}

export interface UseChatMessagesReturn {
  messages: ChatMessage[];
  loadHistory: () => Promise<void>;
  clearHistory: () => void;
  isLoading: boolean;
  /** True once the initial history load for the current session has completed */
  historyLoaded: boolean;
  getUserMessageTexts: () => string[];
}

export function useChatMessages({
  sessionId,
}: UseChatMessagesOptions): UseChatMessagesReturn {
  const messagesMap = useChatStore((s) => s.messages);
  const messages = useMemo(
    () =>
      sessionId ? messagesMap[sessionId] || EMPTY_MESSAGES : EMPTY_MESSAGES,
    [sessionId, messagesMap],
  );
  const addMessage = useChatStore((s) => s.addMessage);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const setHistoryLoaded = useChatStore((s) => s.setHistoryLoaded);
  const historyLoaded = useChatStore((s) => s.historyLoaded);

  const loadHistory = useCallback(async () => {
    if (!sessionId) return;

    // If we're currently streaming into this session (e.g. send() just created
    // it), skip history loading — clearMessages would wipe the live messages.
    // The stream will populate the messages; historyLoaded is still marked true
    // so that reconnect logic can proceed if needed.
    const currentState = useChatStore.getState();
    if (
      currentState.isGenerating &&
      currentState.activeSessionId === sessionId
    ) {
      setHistoryLoaded(true);
      return;
    }

    try {
      const history = await chatApi.getChat(sessionId);

      // Clear existing and reload
      clearMessages(sessionId);

      if (!history.messages?.length) {
        return;
      }

      // Merge tool input+output, then group consecutive non-user messages
      const rawMessages = history.messages as Record<string, unknown>[];
      const merged = mergeHistoryToolMessages(rawMessages);

      let i = 0;
      while (i < merged.length) {
        const msg = merged[i];
        if ((msg.role as string) === "user") {
          addMessage(sessionId, convertBackendMessage(msg));
          i++;
        } else {
          // Group consecutive non-user messages into one assistant ChatMessage
          const groupContent: MessageContent[] = [];
          while (i < merged.length && (merged[i].role as string) !== "user") {
            const converted = convertBackendMessage(merged[i]);
            groupContent.push(...converted.content);
            i++;
          }
          if (groupContent.length > 0) {
            addMessage(sessionId, {
              id: generateId(),
              role: "assistant",
              content: groupContent,
              status: MESSAGE_STATUS.COMPLETED,
              createdAt: Date.now(),
            });
          }
        }
      }
    } catch (err) {
      console.error("Failed to load chat history:", err);
    } finally {
      setHistoryLoaded(true);
    }
  }, [sessionId, addMessage, clearMessages, setHistoryLoaded]);

  // Load history when session changes
  useEffect(() => {
    if (sessionId) {
      loadHistory();
    }
  }, [sessionId, loadHistory]);

  const clearHistory = useCallback(() => {
    if (sessionId) {
      clearMessages(sessionId);
    }
  }, [sessionId, clearMessages]);

  const getUserMessageTexts = useCallback((): string[] => {
    return messages
      .filter((m) => m.role === ROLES.USER)
      .map((m) => extractText(m.content))
      .filter((t) => t.trim().length > 0);
  }, [messages]);

  const isLoading = useChatStore((s) => s.isGenerating);

  return {
    messages,
    loadHistory,
    clearHistory,
    isLoading,
    historyLoaded,
    getUserMessageTexts,
  };
}
