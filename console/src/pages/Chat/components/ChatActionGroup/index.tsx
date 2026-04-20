import React, { useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import { OrderedListOutlined } from "@ant-design/icons";
import {
  SparkHistoryLine,
  SparkNewChatFill,
  SparkSearchLine,
} from "@agentscope-ai/icons";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import ChatSessionDrawer from "../ChatSessionDrawer";
import PlanPanel from "../../../../components/PlanPanel";
import ChatSearchPanel from "../ChatSearchPanel";
import type { Plan } from "../../../../api/types";

interface ChatActionGroupProps {
  onPlanStartExecution?: () => void;
  onPlanCancelled?: () => void;
  onPlanStopped?: () => void;
  onPlanRevised?: (plan: Plan) => void;
  livePlanFromChat?: Plan | null;
  chatStreamsPlan?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  onPlanStartExecution,
  onPlanCancelled,
  onPlanStopped,
  onPlanRevised,
  livePlanFromChat,
  chatStreamsPlan,
}) => {
  const { t } = useTranslation();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
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
      />
      <PlanPanel
        open={planOpen}
        onClose={() => setPlanOpen(false)}
        onStartExecution={onPlanStartExecution}
        onPlanCancelled={onPlanCancelled}
        onPlanStopped={onPlanStopped}
        onPlanRevised={onPlanRevised}
        livePlanFromChat={livePlanFromChat}
        chatStreamsPlan={chatStreamsPlan}
      />
      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
    </Flex>
  );
};

export default ChatActionGroup;
