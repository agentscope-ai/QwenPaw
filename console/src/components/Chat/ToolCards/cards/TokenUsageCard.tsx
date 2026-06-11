import React from "react";
import { useTranslation } from "react-i18next";
import { BarChart2 } from "lucide-react";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

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
      icon={<BarChart2 size={13} />}
      title={title}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default TokenUsageCard;
