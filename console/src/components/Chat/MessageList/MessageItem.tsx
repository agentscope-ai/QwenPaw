import React, { memo } from "react";
import type { ChatMessage } from "../types";
import { MessageContext } from "../context/MessageContext";
import UserMessage from "./UserMessage";
import AssistantMessage from "./AssistantMessage";
import { ROLES } from "../constants";

interface MessageItemProps {
  message: ChatMessage;
  index: number;
  isLast: boolean;
  isStreaming: boolean;
}

const MessageItem: React.FC<MessageItemProps> = memo(
  ({ message, index, isLast, isStreaming }) => {
    const contextValue = { message, isStreaming, index, isLast };

    return (
      <MessageContext.Provider value={contextValue}>
        <div
          className="chat-message-item"
          data-message-id={message.id}
          data-role={message.role}
        >
          {message.role === ROLES.USER ? <UserMessage /> : <AssistantMessage />}
        </div>
      </MessageContext.Provider>
    );
  },
);

MessageItem.displayName = "MessageItem";
export default MessageItem;
