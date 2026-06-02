import React from "react";
import { useTranslation } from "react-i18next";
import { ApiOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface DelegateExternalAgentCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const DelegateExternalAgentCard: React.FC<DelegateExternalAgentCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const runner = (params.runner || "") as string;
  const title = runner
    ? t("tool.delegateExternalAgent", { runner })
    : t("tool.delegateExternalAgentDefault");

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<ApiOutlined />}
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

export default DelegateExternalAgentCard;
