import React from "react";

import { IconButton } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Flex, Tooltip, message } from "antd";
import { Files, Terminal } from "lucide-react";
import styles from "./ChatActionGroup.module.less";

interface ChatActionGroupProps {
  onToggleTerminal?: () => void;
  terminalOpen?: boolean;
  terminalEnabled?: boolean;
  terminalDisabledReason?: string;
  onToggleWorkspace?: () => void;
  workspaceOpen?: boolean;
}

const ChatActionGroup: React.FC<ChatActionGroupProps> = ({
  onToggleTerminal,
  terminalOpen = false,
  terminalEnabled = false,
  terminalDisabledReason = "",
  onToggleWorkspace,
  workspaceOpen = false,
}) => {
  const { t } = useTranslation();

  return (
    <Flex className={styles.actionGroup} gap={8} align="center">
      {onToggleTerminal && (
        <Tooltip title={t("terminal.title")} mouseEnterDelay={0.5}>
          <IconButton
            className={styles.workspaceButton}
            bordered={false}
            aria-label={t("terminal.title")}
            aria-expanded={terminalOpen}
            icon={
              <Terminal
                size={16}
                strokeWidth={1.8}
                style={{ width: 16, height: 16 }}
              />
            }
            style={{
              width: 32,
              height: 32,
              padding: 0,
              ...(terminalOpen ? { color: "var(--app-accent)" } : {}),
            }}
            onClick={() => {
              if (!terminalEnabled) {
                void message.info(
                  t(
                    terminalDisabledReason === "dependency_missing"
                      ? "terminal.dependencyMissing"
                      : terminalDisabledReason
                      ? "terminal.unavailable"
                      : "terminal.authRequired",
                  ),
                );
                return;
              }
              onToggleTerminal();
            }}
          />
        </Tooltip>
      )}
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
