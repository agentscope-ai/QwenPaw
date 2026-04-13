import { useState, useEffect } from "react";
import { Popover, List, Spin, Empty } from "antd";
import { SparkAtLine } from "@agentscope-ai/icons";
import { IconButton } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../stores/agentStore";
import { agentsApi } from "../../api/modules/agents";
import { useAppMessage } from "../../hooks/useAppMessage";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import type { AgentSummary } from "../../api/types/agents";
import styles from "./index.module.less";

interface AgentMentionButtonProps {
  disabled?: boolean;
}

export default function AgentMentionButton({
  disabled = false,
}: AgentMentionButtonProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { agents, setAgents } = useAgentStore();
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (open && agents.length === 0) {
      setLoading(true);
      agentsApi
        .listAgents()
        .then((data) => {
          const sortedAgents = [...data.agents].sort(
            (a, b) => Number(b.enabled) - Number(a.enabled),
          );
          setAgents(sortedAgents);
        })
        .catch((error) => {
          console.error("Failed to load agents:", error);
          message.error(t("agent.loadFailed"));
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, agents.length, setAgents, message, t]);

  const handleSelectAgent = (agent: AgentSummary) => {
    insertMentionText(agent);
    setOpen(false);
  };

  const insertMentionText = (agent: AgentSummary) => {
    const textarea = document.querySelector(
      '.copaw-sender textarea, [class*="sender"] textarea, textarea.ant-input',
    ) as HTMLTextAreaElement;

    if (!textarea) {
      console.warn("Chat input textarea not found");
      return;
    }

    const mentionText = ` @${agent.name}(${agent.id}) `;

    textarea.focus();

    const cursorPosition = textarea.selectionStart ?? textarea.value.length;
    const currentValue = textarea.value;

    const newValue =
      currentValue.slice(0, cursorPosition) +
      mentionText +
      currentValue.slice(cursorPosition);

    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;

    if (nativeInputValueSetter) {
      nativeInputValueSetter.call(textarea, newValue);
    } else {
      textarea.value = newValue;
    }

    textarea.dispatchEvent(new Event("input", { bubbles: true }));

    const newCursorPosition = cursorPosition + mentionText.length;
    textarea.setSelectionRange(newCursorPosition, newCursorPosition);
    textarea.focus();
  };

  const enabledAgents = agents.filter((agent) => agent.enabled);

  const popoverContent = (
    <div className={styles.agentPopoverContent}>
      <div className={styles.popoverHeader}>
        <span className={styles.popoverTitle}>{t("chat.mentionAgent")}</span>
      </div>
      <Spin spinning={loading} size="small">
        {enabledAgents.length > 0 ? (
          <List
            className={styles.agentList}
            dataSource={enabledAgents}
            renderItem={(agent) => (
              <List.Item
                className={styles.agentListItem}
                onClick={() => handleSelectAgent(agent)}
              >
                <div className={styles.agentItem}>
                  <span className={styles.agentName}>
                    {getAgentDisplayName(agent, t)}
                  </span>
                  <span className={styles.agentId}>ID: {agent.id}</span>
                </div>
              </List.Item>
            )}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              loading ? t("common.loading") : t("chat.noEnabledAgents")
            }
          />
        )}
      </Spin>
    </div>
  );

  return (
    <Popover
      content={popoverContent}
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="topLeft"
      overlayClassName={styles.agentPopover}
      arrow={false}
    >
      <IconButton
        disabled={disabled}
        icon={<SparkAtLine />}
        bordered={false}
        title={t("chat.mentionAgent")}
      />
    </Popover>
  );
}
