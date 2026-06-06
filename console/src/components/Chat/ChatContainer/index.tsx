import React, { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ChatContext,
  type ChatContextValue,
  type UserDisplayInfo,
  type AssistantDisplayInfo,
} from "../context/ChatContext";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore } from "../stores/sessionStore";
import { useChatStream } from "../hooks/useChatStream";
import { useToolCards } from "../hooks/useToolCards";
import { SESSION_STATUS } from "../constants";
import type { ChatConfig, ChatInputData, ToolCardRegistry } from "../types";
import styles from "./ChatContainer.module.less";

export interface ChatContainerProps {
  /** Chat API configuration */
  config: ChatConfig;
  /** Agent ID for context */
  agentId?: string;
  /** Custom tool card components */
  toolCards?: ToolCardRegistry;
  /** User display info (name, avatar) */
  userInfo?: UserDisplayInfo;
  /** Assistant display info (name, avatar, model) */
  assistantInfo?: AssistantDisplayInfo;
  /** Children components (MessageList, MessageInput, SessionPanel) */
  children: React.ReactNode;
  /** Custom class name */
  className?: string;
  /** Called when history should be cleared */
  onHistoryClear?: () => void;
  /** Called on stream errors */
  onError?: (error: Error) => void;
}

const ChatContainer: React.FC<ChatContainerProps> = ({
  config,
  agentId,
  toolCards = {},
  userInfo,
  assistantInfo,
  children,
  className,
  onHistoryClear,
  onError,
}) => {
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const clearMessages = useChatStore((s) => s.clearMessages);

  const { registry } = useToolCards({ cards: toolCards });

  const handleHistoryClear = useCallback(() => {
    if (activeSessionId) {
      clearMessages(activeSessionId);
    }
    onHistoryClear?.();
  }, [activeSessionId, clearMessages, onHistoryClear]);

  const { send, cancel, reconnect } = useChatStream({
    config,
    sessionId: activeSessionId,
    onHistoryClear: handleHistoryClear,
    onError,
  });

  // Auto-reconnect when switching to a session that is still running.
  // Serialized: wait for historyLoaded THEN check status and reconnect.
  // This mirrors Chat V1's approach — no concurrency between history load
  // and reconnect, so no need for complex "save live messages" logic.
  const reconnectAttemptedRef = useRef<string | null>(null);
  const isGenerating = useChatStore((s) => s.isGenerating);
  const historyLoaded = useChatStore((s) => s.historyLoaded);
  const sessions = useSessionStore((s) => s.sessions);

  const currentSessionStatus = useMemo(
    () => sessions.find((s) => s.id === activeSessionId)?.status,
    [sessions, activeSessionId],
  );

  useEffect(() => {
    if (!activeSessionId || !historyLoaded) return;

    // If we're already generating (e.g. send just created this session),
    // don't reconnect — we're already streaming.
    if (isGenerating) return;

    // Only attempt reconnect once per session id to avoid loops
    if (reconnectAttemptedRef.current === activeSessionId) return;

    if (currentSessionStatus === SESSION_STATUS.RUNNING) {
      reconnectAttemptedRef.current = activeSessionId;
      reconnect();
    }
  }, [
    activeSessionId,
    historyLoaded,
    currentSessionStatus,
    reconnect,
    isGenerating,
  ]);

  const handleSend = useCallback(
    (input: ChatInputData) => {
      send(input);
    },
    [send],
  );

  const handleCancel = useCallback(() => {
    cancel();
  }, [cancel]);

  const handleReconnect = useCallback(() => {
    reconnect();
  }, [reconnect]);

  const contextValue = useMemo<ChatContextValue>(
    () => ({
      config,
      onSend: handleSend,
      onCancel: handleCancel,
      onReconnect: handleReconnect,
      toolCardRegistry: registry,
      agentId,
      userInfo,
      assistantInfo,
    }),
    [
      config,
      handleSend,
      handleCancel,
      handleReconnect,
      registry,
      agentId,
      userInfo,
      assistantInfo,
    ],
  );

  return (
    <ChatContext.Provider value={contextValue}>
      <div className={`${styles.chatContainer} ${className || ""}`}>
        {children}
      </div>
    </ChatContext.Provider>
  );
};

export default ChatContainer;
