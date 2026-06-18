/**
 * ShellCard — renders shell/terminal tool calls with command + output.
 * Self-contained: no dependency on ShellExecutionCard.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { CodeOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

export interface ShellCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ShellCard: React.FC<ShellCardProps> = ({ content, isStreaming }) => {
  const { t } = useTranslation();
  const command =
    (content.params?.command as string) ||
    (content.params?.cmd as string) ||
    "";
  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      icon={<CodeOutlined />}
      title={command ? t("tool.shell", { command }) : t("tool.shellDefault")}
      content={content}
      isStreaming={isStreaming}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default ShellCard;
