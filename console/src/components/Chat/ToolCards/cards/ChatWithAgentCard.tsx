import React from "react";
import { useTranslation } from "react-i18next";
import { MessageSquare as MessageOutlined } from "lucide-react";
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

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<MessageOutlined size="1em" />}
      title={title}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default ChatWithAgentCard;
