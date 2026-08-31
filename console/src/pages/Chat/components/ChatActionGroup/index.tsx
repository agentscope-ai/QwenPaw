import React from "react";

import { IconButton } from "@agentscope-ai/design";
import { SparkHistoryLine, SparkNewChatFill } from "@agentscope-ai/icons";
import { MoreOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Dropdown, Flex, Tooltip } from "antd";
import { Files } from "lucide-react";
import type { MenuProps } from "antd";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import styles from "./ChatActionGroup.module.less";

interface ChatActionGroupProps {
  /** Callback to toggle the right-side history panel */
  onToggleHistory?: () => void;
  /** Whether the history panel is currently visible */
  historyOpen?: boolean;
  onToggleWorkspace?: () => void;
  workspaceOpen?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  onToggleHistory,
  historyOpen = false,
  onToggleWorkspace,
  workspaceOpen = false,
}) => {
  const { t } = useTranslation();

  const createNewSession = useCreateNewSession();

  // Compact mode follows the viewport: collapse secondary actions only on
  // mobile. This saves space on phones while keeping actions visible on desktop.
  const isCompact = useIsMobile();

  // Build the compact overflow menu for optional secondary actions.
  const moreItems: MenuProps["items"] = [];
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

  return (
    <Flex className={styles.actionGroup} gap={8} align="center">
      {/* Essential actions always visible */}
      <Tooltip title={t("chat.newChatTooltip")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          icon={<SparkNewChatFill />}
          onClick={createNewSession}
        />
      </Tooltip>
      {onToggleWorkspace && (
        <Tooltip
          title={t(
            workspaceOpen ? "files.closeWorkspace" : "files.openWorkspace",
          )}
          mouseEnterDelay={0.5}
        >
          <IconButton
            className={styles.workspaceButton}
            bordered={false}
            aria-label={t(
              workspaceOpen ? "files.closeWorkspace" : "files.openWorkspace",
            )}
            aria-pressed={workspaceOpen}
            icon={
              <Files
                size={16}
                strokeWidth={2}
                style={{ width: 16, height: 16 }}
              />
            }
            style={{
              width: 32,
              height: 32,
              padding: 0,
              ...(workspaceOpen
                ? { color: "var(--color-primary, #ff9d4d)" }
                : {}),
            }}
            onClick={onToggleWorkspace}
          />
        </Tooltip>
      )}

      {/* History is inline when not compact. */}
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
      {/* Compact mode: collapse History into the overflow menu. */}
      {isCompact && moreItems.length > 0 && (
        <Dropdown
          menu={{ items: moreItems }}
          trigger={["click"]}
          placement="bottomRight"
        >
          <IconButton bordered={false} icon={<MoreOutlined />} />
        </Dropdown>
      )}
    </Flex>
  );
};

export default ChatActionGroup;
