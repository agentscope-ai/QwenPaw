import React, { useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import { SparkHistoryLine, SparkNewChatFill } from "@agentscope-ai/icons";
import { OrderedListOutlined } from "@ant-design/icons";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import ChatSessionDrawer from "../ChatSessionDrawer";
import PlanPanel from "../../../../components/PlanPanel";

interface ChatActionGroupProps {
  onPlanStartExecution?: () => void;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  onPlanStartExecution,
}) => {
  const { t } = useTranslation();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const { createSession } = useChatAnywhereSessions();

  return (
    <Flex gap={8} align="center">
      <Tooltip title={t("plan.title", "Plan")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<OrderedListOutlined />}
          onClick={() => setPlanOpen(true)}
        />
      </Tooltip>
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
          onClick={() => setHistoryOpen(true)}
        />
      </Tooltip>
      <ChatSessionDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
      />
      <PlanPanel
        open={planOpen}
        onClose={() => setPlanOpen(false)}
        onStartExecution={onPlanStartExecution}
      />
    </Flex>
  );
};

export default ChatActionGroup;
