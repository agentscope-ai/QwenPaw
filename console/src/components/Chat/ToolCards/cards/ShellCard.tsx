/**
 * ShellCard — renders shell/terminal tool calls with command + output.
 * Self-contained: no dependency on ShellExecutionCard.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { Code as CodeOutlined } from "lucide-react";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

export interface ShellCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const COMMAND_FALLBACK_MAX_LENGTH = 120;
const COMMAND_FALLBACK_SEPARATOR = " … ";

const compactCommandFallback = (command: string): string => {
  if (command.length <= COMMAND_FALLBACK_MAX_LENGTH) {
    return command;
  }

  const availableLength =
    COMMAND_FALLBACK_MAX_LENGTH - COMMAND_FALLBACK_SEPARATOR.length;
  const headLength = Math.ceil(availableLength / 2);
  const tailLength = Math.floor(availableLength / 2);
  return `${command.slice(
    0,
    headLength,
  )}${COMMAND_FALLBACK_SEPARATOR}${command.slice(-tailLength)}`;
};

const ShellCard: React.FC<ShellCardProps> = ({ content, isStreaming }) => {
  const { t } = useTranslation();
  const command =
    (content.params?.command as string) ||
    (content.params?.cmd as string) ||
    "";
  const intent =
    (content.params?.title as string) || compactCommandFallback(command);
  const isCompleted = content.status === "done";
  const title = intent
    ? t(isCompleted ? "tool.shellCompleted" : "tool.shell", {
        command: intent,
      })
    : t(isCompleted ? "tool.shellCompletedDefault" : "tool.shellDefault");

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<CodeOutlined size="1em" />}
        title={title}
      />
    );
  }

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      icon={<CodeOutlined size="1em" />}
      title={title}
      content={content}
      isStreaming={isStreaming}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default ShellCard;
