import React from "react";
import { useContextSelector } from "use-context-selector";
import { ChatAnywhereSessionsContext } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereSessionsContext.js";
import type { IAgentScopeRuntimeWebUISession } from "@agentscope-ai/chat";
import type { IAgentScopeRuntimeWebUISessionsContext } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/types/ISessions";
import styles from "./index.module.less";

const ChatHeaderTitle: React.FC = () => {
  const sessions = useContextSelector(
    ChatAnywhereSessionsContext,
    (v: IAgentScopeRuntimeWebUISessionsContext) => v.sessions,
  );
  const currentSessionId = useContextSelector(
    ChatAnywhereSessionsContext,
    (v: IAgentScopeRuntimeWebUISessionsContext) => v.currentSessionId,
  );
  const currentSession = sessions.find(
    (s: IAgentScopeRuntimeWebUISession) => s.id === currentSessionId,
  );
  const chatName = currentSession?.name || "New Chat";

  return <span className={styles.chatName}>{chatName}</span>;
};

export default ChatHeaderTitle;
