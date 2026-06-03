import React, { useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkHistoryLine,
  SparkNewChatFill,
  SparkSearchLine,
} from "@agentscope-ai/icons";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import ChatSessionDrawer from "../ChatSessionDrawer";
import ChatSearchPanel from "../ChatSearchPanel";
import PlanPanel from "../../../../components/PlanPanel";

const PlanIcon = () => (
  <svg
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </svg>
);

const PINNED_STORAGE_KEY = "qwenpaw_history_drawer_pinned";

interface ChatActionGroupProps {
  planEnabled?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  planEnabled = false,
}) => {
  const { t } = useTranslation();

  const [historyPinned, setHistoryPinned] = useState(() => {
    try {
      return localStorage.getItem(PINNED_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  // If pinned, auto-open drawer on mount
  const [historyOpen, setHistoryOpen] = useState(historyPinned);

  const handlePinChange = (pinned: boolean) => {
    setHistoryPinned(pinned);
    try {
      if (pinned) {
        localStorage.setItem(PINNED_STORAGE_KEY, "true");
      } else {
        localStorage.removeItem(PINNED_STORAGE_KEY);
      }
    } catch {
      // storage full or unavailable
    }
  };

  const [searchOpen, setSearchOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const { createSession } = useChatAnywhereSessions();

  return (
    <Flex gap={8} align="center">
      {planEnabled && (
        <Tooltip title={t("plan.title", "Plan")} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<PlanIcon />}
            onClick={() => setPlanOpen(true)}
          />
        </Tooltip>
      )}
      <Tooltip title={t("chat.newChatTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkNewChatFill />}
          onClick={() => createSession()}
        />
      </Tooltip>
      <Tooltip title={t("chat.searchTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkSearchLine />}
          onClick={() => setSearchOpen(true)}
        />
      </Tooltip>
      <Tooltip title={t("chat.chatHistoryTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkHistoryLine />}
          onClick={() => setHistoryOpen(true)}
        />
      </Tooltip>
      <ChatSessionDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        pinned={historyPinned}
        onPinChange={handlePinChange}
      />
      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
      {planEnabled && (
        <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
      )}
    </Flex>
  );
};

export default ChatActionGroup;
