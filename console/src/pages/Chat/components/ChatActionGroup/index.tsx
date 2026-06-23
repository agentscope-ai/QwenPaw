import React, { useState } from "react";

import { IconButton } from "@agentscope-ai/design";
import {
  SparkHistoryLine,
  SparkNewChatFill,
  SparkSearchLine,
} from "@agentscope-ai/icons";
import {
  ExpandAltOutlined,
  CompressOutlined,
  MoreOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Dropdown, Flex, Tooltip } from "antd";
import type { MenuProps } from "antd";
import ChatSearchPanel from "../ChatSearchPanel";
import PlanPanel from "../../../../components/PlanPanel";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import { useIsMobile } from "../../../../hooks/useIsMobile";

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
  const createNewSession = useCreateNewSession();

  // Compact mode follows the viewport: collapse secondary actions only on
  // mobile. This keeps Plan visible on desktop while saving space on phones.
  const isCompact = useIsMobile();

  // Build "more" dropdown items for compact mode: Plan, History, WideMode.
  const moreItems: MenuProps["items"] = [];
  if (planEnabled) {
    moreItems.push({
      key: "plan",
      icon: <PlanIcon />,
      label: (
        <div style={{ textAlign: "center" }}>{t("plan.title", "Plan")}</div>
      ),
      onClick: () => setPlanOpen(true),
    });
  }
  if (onToggleHistory) {
    moreItems.push({
      key: "history",
      icon: <SparkHistoryLine />,
      label: (
        <div style={{ textAlign: "center" }}>
          {t("chat.chatHistoryTooltip")}
        </div>
      ),
      onClick: () => onToggleHistory(),
    });
  }
  if (onToggleWideMode) {
    moreItems.push({
      key: "wideMode",
      icon: isWideMode ? <CompressOutlined /> : <ExpandAltOutlined />,
      label: (
        <div style={{ textAlign: "center" }}>
          {isWideMode ? t("chat.normalModeTooltip") : t("chat.wideModeTooltip")}
        </div>
      ),
      onClick: () => onToggleWideMode(),
    });
  }

  return (
    <Flex gap={8} align="center">
      {/* Plan icon: only render inline when NOT compact */}
      {!isCompact && planEnabled && (
        <Tooltip title={t("plan.title", "Plan")} mouseEnterDelay={0.5}>
          <IconButton
            bordered={false}
            icon={<PlanIcon />}
            onClick={() => setPlanOpen(true)}
          />
        </Tooltip>
      )}

      {/* Essential actions always visible */}
      <Tooltip title={t("chat.newChatTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkNewChatFill />}
          onClick={createNewSession}
        />
      </Tooltip>
      <Tooltip title={t("chat.searchTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkSearchLine />}
          onClick={() => setSearchOpen(true)}
        />
      </Tooltip>

      {/* History + WideMode: inline when NOT compact */}
      {!isCompact && onToggleHistory && (
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
      {!isCompact && onToggleWideMode && (
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

      {/* Compact mode: collapse Plan/History/WideMode into more dropdown */}
      {isCompact && moreItems.length > 0 && (
        <Dropdown
          menu={{ items: moreItems }}
          trigger={["click"]}
          placement="bottomRight"
        >
          <IconButton bordered={false} icon={<MoreOutlined />} />
        </Dropdown>
      )}

      <ChatSearchPanel open={searchOpen} onClose={() => setSearchOpen(false)} />
      {planEnabled && (
        <PlanPanel open={planOpen} onClose={() => setPlanOpen(false)} />
      )}
    </Flex>
  );
};

export default ChatActionGroup;
