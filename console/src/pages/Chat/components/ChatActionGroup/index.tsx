import React from "react";

import { IconButton } from "@agentscope-ai/design";
import {
  SparkNewChatLine,
  SparkVoiceChat01Line,
} from "@agentscope-ai/icons";
import { DownOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Dropdown, Flex, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { Files } from "lucide-react";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import styles from "./ChatActionGroup.module.less";

interface ChatActionGroupProps {
  /** Start a new dedicated realtime Voice Chat. */
  onCreateVoiceChat?: () => void;
  /** Voice Chat is unavailable while capability discovery or startup runs. */
  voiceChatDisabled?: boolean;
  onToggleWorkspace?: () => void;
  workspaceOpen?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  onCreateVoiceChat,
  voiceChatDisabled = false,
  onToggleWorkspace,
  workspaceOpen = false,
}) => {
  const { t } = useTranslation();

  const createNewSession = useCreateNewSession();

  const newChatItems: MenuProps["items"] = onCreateVoiceChat
    ? [
        {
          key: "chat",
          icon: <SparkNewChatLine size={18} />,
          label: t("chat.newTask"),
          onClick: createNewSession,
        },
        {
          key: "voice",
          icon: <SparkVoiceChat01Line />,
          label: t("realtimeVoice.newChat"),
          disabled: voiceChatDisabled,
          onClick: onCreateVoiceChat,
        },
      ]
    : [];

  return (
    <Flex className={styles.actionGroup} gap={8} align="center">
      <Flex gap={0} className={styles.newChatSplitButton}>
        <Tooltip title={t("chat.newTask")} mouseEnterDelay={0.5}>
          <IconButton
            className={onCreateVoiceChat ? styles.newChatPrimary : undefined}
            bordered={false}
            aria-label={t("chat.newTask")}
            icon={<SparkNewChatLine size={18} />}
            style={{ width: 32, height: 32, padding: 0 }}
            onClick={createNewSession}
          />
        </Tooltip>
        {onCreateVoiceChat && (
          <Dropdown
            menu={{ items: newChatItems }}
            trigger={["click"]}
            placement="bottomRight"
          >
            <IconButton
              className={styles.newChatMenu}
              bordered={false}
              aria-label={t("chat.newChatMenu")}
              icon={<DownOutlined />}
              style={{ height: 32 }}
            />
          </Dropdown>
        )}
      </Flex>
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
              ...(workspaceOpen ? { color: "var(--app-accent)" } : {}),
            }}
            onClick={onToggleWorkspace}
          />
        </Tooltip>
      )}
    </Flex>
  );
};

export default ChatActionGroup;
