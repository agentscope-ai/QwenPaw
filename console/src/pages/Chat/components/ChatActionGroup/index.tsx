import React, { useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import { SparkHistoryLine, SparkNewChatFill } from "@agentscope-ai/icons";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import ChatSessionDrawer from "../ChatSessionDrawer";
import { Flex } from "antd";

const ChatActionGroup: React.FC = () => {
  const [open, setOpen] = useState(false);
  const { createSession } = useChatAnywhereSessions();

  return (
    <Flex gap={8} align="center">
      <IconButton
        bordered={false}
        icon={<SparkNewChatFill />}
        onClick={() => createSession()}
      />
      <IconButton
        bordered={false}
        icon={<SparkHistoryLine />}
        onClick={() => setOpen(true)}
      />
      <ChatSessionDrawer open={open} onClose={() => setOpen(false)} />
    </Flex>
  );
};

export default ChatActionGroup;
