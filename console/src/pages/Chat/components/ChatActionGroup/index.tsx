import React, { useEffect, useState } from "react";
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
import { planApi } from "../../../../api/modules/plan";
import { useAgentStore } from "../../../../stores/agentStore";

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

const ChatActionGroup: React.FC = () => {
  const { t } = useTranslation();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [planEnabled, setPlanEnabled] = useState(false);
  const { createSession } = useChatAnywhereSessions();
  const { selectedAgent } = useAgentStore();

  useEffect(() => {
    let cancelled = false;
    planApi
      .getPlanConfig()
      .then((cfg) => {
        if (!cancelled) setPlanEnabled(cfg.enabled);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

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
      />
      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
      {planEnabled && (
        <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
      )}
    </Flex>
  );
};

export default ChatActionGroup;
