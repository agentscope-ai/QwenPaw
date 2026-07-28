import React from "react";
import { useTranslation } from "react-i18next";
import { MessageOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

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

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<MessageOutlined />}
      title={title}
      renderBody={() => {
        const resultText = stringifyResult(content.result);
        return resultText ? (
          <DefaultBlock title="Output" content={resultText} />
        ) : null;
      }}
    />
  );
};

export default ChatWithAgentCard;
