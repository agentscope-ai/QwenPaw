import React from "react";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { useCodingMode } from "../../../../stores/codingModeStore";
import styles from "./index.module.less";

const ChatHeaderTitle: React.FC = () => {
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const { codingMode } = useCodingMode();
  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const chatName = currentSession?.name || "New Chat";

  const className = codingMode
    ? `${styles.chatName} ${styles.chatNameCoding}`
    : styles.chatName;

  return <span className={className}>{chatName}</span>;
};

export default ChatHeaderTitle;
