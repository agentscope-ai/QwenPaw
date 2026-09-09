import React, { useState } from "react";
import { Dropdown } from "antd";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { Check } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useCodingMode } from "../../../../stores/codingModeStore";
import type { ExtendedSession } from "../../../../stores/sessionListStore";
import { buildChatPath } from "../../../../utils/sessionRoute";
import sessionApi from "../../sessionApi";
import styles from "./index.module.less";

const ChatHeaderTitle: React.FC = () => {
  const { sessions, currentSessionId } = useChatAnywhereSessionsState();
  const navigate = useNavigate();
  const { codingMode } = useCodingMode();
  const currentSession = sessions.find(
    (s) =>
      !!currentSessionId &&
      (s.id === currentSessionId ||
        (s as ExtendedSession).realId === currentSessionId),
  );
  const chatName = currentSession?.name || "New Chat";

  const [open, setOpen] = useState(false);

  const handleSessionClick = (sessionId: string) => {
    navigate(buildChatPath(sessionApi.getEffectiveSessionId(sessionId)), {
      replace: true,
    });
    setOpen(false);
  };

  const menuItems = sessions.map((session) => ({
    key: session.id,
    label: (
      <div className={styles.menuItem}>
        <span className={styles.menuItemName}>
          {session.name || "New Chat"}
        </span>
        {session === currentSession && (
          <Check className={styles.menuItemActive} size={16} aria-hidden />
        )}
      </div>
    ),
    onClick: () => handleSessionClick(session.id),
  }));

  const className = codingMode
    ? `${styles.chatName} ${styles.chatNameCoding}`
    : styles.chatName;

  const titleContent = (
    <span className={className} title={chatName}>
      {chatName}
    </span>
  );

  if (sessions.length <= 1) {
    return titleContent;
  }

  return (
    <Dropdown
      menu={{ items: menuItems }}
      open={open}
      onOpenChange={setOpen}
      trigger={["click"]}
      placement="bottomLeft"
      overlayClassName={styles.sessionDropdown}
    >
      <button
        type="button"
        className={styles.trigger}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {titleContent}
      </button>
    </Dropdown>
  );
};

export default ChatHeaderTitle;
