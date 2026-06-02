import React from "react";
import { useTranslation } from "react-i18next";
import { DashboardOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface TokenUsageCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const TokenUsageCard: React.FC<TokenUsageCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const title = t("tool.getTokenUsage");
  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<DashboardOutlined />}
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

export default TokenUsageCard;
