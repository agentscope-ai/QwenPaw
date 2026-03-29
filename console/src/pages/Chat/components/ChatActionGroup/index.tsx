import React, { useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import { SparkHistoryLine, SparkNewChatFill } from "@agentscope-ai/icons";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import ChatSessionDrawer from "../ChatSessionDrawer";

const ChatActionGroup: React.FC = () => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
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
      <Tooltip title={t("chat.chatHistoryTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkHistoryLine />}
          onClick={() => setOpen(true)}
        />
      </Tooltip>
      <ChatSessionDrawer open={open} onClose={() => setOpen(false)} />
    </Flex>
  );
};

export default ChatActionGroup;
