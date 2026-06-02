import React from "react";
import { useTranslation } from "react-i18next";
import { MessageOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface ChatWithAgentCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ChatWithAgentCard: React.FC<ChatWithAgentCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const agent = (params.to_agent || "") as string;
  const title = agent
    ? t("tool.chatWithAgent", { agent })
    : t("tool.chatWithAgentDefault");

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<MessageOutlined />}
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

export default ChatWithAgentCard;
