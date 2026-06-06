import { createContext, useContext } from "react";
import type { ChatConfig, ChatInputData, ToolCardRegistry } from "../types";

/** Display info for the user side */
export interface UserDisplayInfo {
  name?: string;
  avatar?: string;
}

/** Display info for the assistant/agent side */
export interface AssistantDisplayInfo {
  name?: string;
  avatar?: string;
  model?: string;
}

export interface ChatContextValue {
  /** Chat configuration */
  config: ChatConfig;
  /** Send a message */
  onSend: (input: ChatInputData) => void;
  /** Cancel current generation */
  onCancel: () => void;
  /** Reconnect to a running session */
  onReconnect: () => void;
  /** Registered tool card components */
  toolCardRegistry: ToolCardRegistry;
  /** Current agent ID */
  agentId?: string;
  /** User display info (name, avatar) */
  userInfo?: UserDisplayInfo;
  /** Assistant display info (name, avatar, model) */
  assistantInfo?: AssistantDisplayInfo;
}

export const ChatContext = createContext<ChatContextValue | null>(null);

export function useChatContext(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error("useChatContext must be used within a ChatContainer");
  }
  return ctx;
}
