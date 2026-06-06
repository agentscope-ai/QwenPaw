import { create } from "zustand";
import type {
  ChatMessage,
  MessageContent,
  MessageStatus,
  MessageMetadata,
} from "../types";
import { MESSAGE_STATUS } from "../constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatState {
  /** Messages grouped by session ID */
  messages: Record<string, ChatMessage[]>;
  /** Currently active session */
  activeSessionId: string | null;
  /** Whether the assistant is currently generating */
  isGenerating: boolean;
  /** ID of the message currently being streamed */
  streamingMessageId: string | null;
  /** Whether initial history has been loaded for the active session */
  historyLoaded: boolean;

  // Actions
  setActiveSession: (sessionId: string | null) => void;
  setGenerating: (generating: boolean) => void;
  setHistoryLoaded: (loaded: boolean) => void;

  /** Add a complete message to a session */
  addMessage: (sessionId: string, message: ChatMessage) => void;
  /** Update specific fields of a message */
  updateMessage: (
    sessionId: string,
    messageId: string,
    patch: Partial<ChatMessage>,
  ) => void;
  /** Append text to a streaming message's text content */
  appendStreamText: (
    sessionId: string,
    messageId: string,
    text: string,
  ) => void;
  /** Append or update content blocks in a streaming message */
  updateStreamContent: (
    sessionId: string,
    messageId: string,
    content: MessageContent[],
  ) => void;
  /** Set streaming message status */
  setStreamingMessage: (messageId: string | null) => void;
  /** Finalize a streaming message */
  finalizeMessage: (
    sessionId: string,
    messageId: string,
    metadata?: MessageMetadata,
  ) => void;
  /** Clear all messages for a session */
  clearMessages: (sessionId: string) => void;
  /** Remove a specific message */
  removeMessage: (sessionId: string, messageId: string) => void;
  /** Get messages for a session */
  getMessages: (sessionId: string) => ChatMessage[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useChatStore = create<ChatState>((set, get) => ({
  messages: {},
  activeSessionId: null,
  isGenerating: false,
  streamingMessageId: null,
  historyLoaded: false,

  setActiveSession: (sessionId) =>
    set({ activeSessionId: sessionId, historyLoaded: false }),

  setGenerating: (generating) => set({ isGenerating: generating }),

  setHistoryLoaded: (loaded) => set({ historyLoaded: loaded }),

  addMessage: (sessionId, message) =>
    set((state) => {
      const current = state.messages[sessionId] || [];
      return {
        messages: {
          ...state.messages,
          [sessionId]: [
            ...current,
            { ...message, id: message.id || generateId() },
          ],
        },
      };
    }),

  updateMessage: (sessionId, messageId, patch) =>
    set((state) => {
      const current = state.messages[sessionId];
      if (!current) return state;
      return {
        messages: {
          ...state.messages,
          [sessionId]: current.map((msg) =>
            msg.id === messageId ? { ...msg, ...patch } : msg,
          ),
        },
      };
    }),

  appendStreamText: (sessionId, messageId, text) =>
    set((state) => {
      const current = state.messages[sessionId];
      if (!current) return state;
      return {
        messages: {
          ...state.messages,
          [sessionId]: current.map((msg) => {
            if (msg.id !== messageId) return msg;
            const content = [...msg.content];
            // Find last text content block
            let lastTextIdx = -1;
            for (let i = content.length - 1; i >= 0; i--) {
              if (content[i].type === "text") {
                lastTextIdx = i;
                break;
              }
            }
            if (lastTextIdx >= 0) {
              const lastText = content[lastTextIdx];
              if (lastText.type === "text") {
                return {
                  ...msg,
                  content: content.map((c, idx) =>
                    idx === lastTextIdx && c.type === "text"
                      ? { ...c, text: c.text + text }
                      : c,
                  ),
                };
              }
            }
            return {
              ...msg,
              content: [...content, { type: "text" as const, text }],
            };
          }),
        },
      };
    }),

  updateStreamContent: (sessionId, messageId, newContent) =>
    set((state) => {
      const current = state.messages[sessionId];
      if (!current) return state;
      return {
        messages: {
          ...state.messages,
          [sessionId]: current.map((msg) =>
            msg.id === messageId ? { ...msg, content: newContent } : msg,
          ),
        },
      };
    }),

  setStreamingMessage: (messageId) => set({ streamingMessageId: messageId }),

  finalizeMessage: (sessionId, messageId, metadata) =>
    set((state) => {
      const current = state.messages[sessionId];
      if (!current) return state;
      return {
        messages: {
          ...state.messages,
          [sessionId]: current.map((msg) =>
            msg.id === messageId
              ? {
                  ...msg,
                  status: MESSAGE_STATUS.COMPLETED as MessageStatus,
                  metadata: { ...msg.metadata, ...metadata },
                }
              : msg,
          ),
        },
        streamingMessageId:
          state.streamingMessageId === messageId
            ? null
            : state.streamingMessageId,
        isGenerating:
          state.streamingMessageId === messageId ? false : state.isGenerating,
      };
    }),

  clearMessages: (sessionId) =>
    set((state) => ({
      messages: { ...state.messages, [sessionId]: [] },
    })),

  removeMessage: (sessionId, messageId) =>
    set((state) => {
      const current = state.messages[sessionId];
      if (!current) return state;
      return {
        messages: {
          ...state.messages,
          [sessionId]: current.filter((msg) => msg.id !== messageId),
        },
      };
    }),

  getMessages: (sessionId) => get().messages[sessionId] || [],
}));
