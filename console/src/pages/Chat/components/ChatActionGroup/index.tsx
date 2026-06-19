import React, { useEffect, useRef, useState } from "react";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkHistoryLine,
  SparkNewChatFill,
  SparkSearchLine,
} from "@agentscope-ai/icons";
import { ExpandAltOutlined, CompressOutlined } from "@ant-design/icons";
import {
  useChatAnywhereSessions,
  useChatAnywhereSessionsState,
} from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import ChatSearchPanel from "../ChatSearchPanel";
import PlanPanel from "../../../../components/PlanPanel";
import { planApi, subscribePlanUpdates } from "../../../../api/modules/plan";

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

interface ChatActionGroupProps {
  planEnabled?: boolean;
  /** Callback to toggle the right-side history panel */
  onToggleHistory?: () => void;
  /** Whether the history panel is currently visible */
  historyOpen?: boolean;
  isWideMode?: boolean;
  onToggleWideMode?: () => void;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  planEnabled = false,
  onToggleHistory,
  historyOpen = false,
  isWideMode = false,
  onToggleWideMode,
}) => {
  const { t } = useTranslation();

  const [searchOpen, setSearchOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [hasActivePlan, setHasActivePlan] = useState(false);
  const prevHasPlanRef = useRef(false);

  const { createSession } = useChatAnywhereSessions();
  const { currentSessionId } = useChatAnywhereSessionsState();

  // Fetch initial plan status when session changes
  useEffect(() => {
    const checkPlan = async () => {
      const sid = (window as any).currentSessionId || "";
      try {
        const data = await planApi.getCurrentPlan(sid || undefined);
        const hasPlan = data !== null;
        setHasActivePlan(hasPlan);
        prevHasPlanRef.current = hasPlan;
      } catch {
        // ignore
      }
    };
    checkPlan();
  }, [currentSessionId]);

  // Subscribe to real-time plan updates
  useEffect(() => {
    const unsub = subscribePlanUpdates((updatedPlan, eventSessionId) => {
      const mySid = (window as any).currentSessionId || "";
      if (eventSessionId && mySid && eventSessionId !== mySid) return;

      const hasPlan = updatedPlan !== null;
      setHasActivePlan(hasPlan);

      if (hasPlan && !prevHasPlanRef.current) {
        setPlanOpen(true);
      }
      prevHasPlanRef.current = hasPlan;
    });

    return unsub;
  }, []);

  return (
    <Flex gap={8} align="center">
      {(planEnabled || hasActivePlan) && (
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
      {onToggleHistory && (
        <Tooltip title={t("chat.chatHistoryTooltip")} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<SparkHistoryLine />}
            style={
              historyOpen
                ? { color: "var(--color-primary, #ff9d4d)" }
                : undefined
            }
            onClick={onToggleHistory}
          />
        </Tooltip>
      )}
      {onToggleWideMode && (
        <Tooltip
          title={
            isWideMode ? t("chat.normalModeTooltip") : t("chat.wideModeTooltip")
          }
          mouseEnterDelay={0.5}
        >
          <IconButton
            bordered={false}
            icon={isWideMode ? <CompressOutlined /> : <ExpandAltOutlined />}
            onClick={onToggleWideMode}
          />
        </Tooltip>
      )}
      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
      {(planEnabled || hasActivePlan) && (
        <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
      )}
    </Flex>
  );
};

export default ChatActionGroup;
