import React, { useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import { SparkHistoryLine, SparkNewChatFill, SparkSearchLine } from "@agentscope-ai/icons";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import ChatSessionDrawer from "../ChatSessionDrawer";
import ChatSearchPanel from "../ChatSearchPanel";

const ChatActionGroup: React.FC = () => {
  const { t } = useTranslation();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const { createSession } = useChatAnywhereSessions();

  return (
    <Flex gap={8} align="center">
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
      <ChatSessionDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
    </Flex>
  );
};

export default ChatActionGroup;
