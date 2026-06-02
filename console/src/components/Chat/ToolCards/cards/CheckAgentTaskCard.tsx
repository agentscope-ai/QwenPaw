import React from "react";
import { useTranslation } from "react-i18next";
import { SyncOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface CheckAgentTaskCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const CheckAgentTaskCard: React.FC<CheckAgentTaskCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const agent = (params.agent_id || params.to_agent || "") as string;
  const taskId = (params.task_id || "") as string;

  let title: string;
  if (agent && taskId) {
    title = t("tool.checkAgentTask", { agent, taskId });
  } else if (agent) {
    title = t("tool.checkAgentTaskAgent", { agent });
  } else {
    title = t("tool.checkAgentTaskDefault");
  }

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<SyncOutlined />}
      title={title}
    >
      {resultText && (
        <div className={styles.toolCallResultMd}>
          <Markdown content={resultText} />
        </div>
      )}
    </ToolCardShell>
  );
};

export default CheckAgentTaskCard;
