import React from "react";

import { IconButton } from "@agentscope-ai/design";
import { SparkNewChatLine } from "@agentscope-ai/icons";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip } from "antd";
import { Files } from "lucide-react";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import styles from "./ChatActionGroup.module.less";

interface ChatActionGroupProps {
  onToggleWorkspace?: () => void;
  workspaceOpen?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  onToggleWorkspace,
  workspaceOpen = false,
}) => {
  const { t } = useTranslation();

  const createNewSession = useCreateNewSession();

  return (
    <Flex className={styles.actionGroup} gap={8} align="center">
      <Tooltip title={t("chat.newTask")} mouseEnterDelay={0.5}>
        <IconButton
          bordered={false}
          aria-label={t("chat.newTask")}
          icon={<SparkNewChatLine size={18} />}
          style={{ width: 32, height: 32, padding: 0 }}
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
