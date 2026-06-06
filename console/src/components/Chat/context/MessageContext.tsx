import { createContext, useContext } from "react";
import type { ChatMessage } from "../types";

export interface MessageContextValue {
  /** The current message being rendered */
  message: ChatMessage;
  /** Whether this message is currently streaming */
  isStreaming: boolean;
  /** Index in the message list */
  index: number;
  /** Whether this is the last message */
  isLast: boolean;
}

export const MessageContext = createContext<MessageContextValue | null>(null);

export function useMessageContext(): MessageContextValue {
  const ctx = useContext(MessageContext);
  if (!ctx) {
    throw new Error("useMessageContext must be used within a MessageItem");
  }
  return ctx;
}
