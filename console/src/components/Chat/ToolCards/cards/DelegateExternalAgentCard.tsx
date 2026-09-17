import React from "react";
import { useTranslation } from "react-i18next";
import { ApiOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

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
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default DelegateExternalAgentCard;
