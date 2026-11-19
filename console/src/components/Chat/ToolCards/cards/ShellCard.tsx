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
  const pptStep = command.match(
    /(?:^|[\\/"'\s])(prepare_slide_prompts|record_slide_dispatch|record_slide_result|record_slide_blocker|slide_job_status|assemble_ppt)\.py(?=["'\s]|$)/i,
  );
  const title = pptStep
    ? t(`tool.pptSteps.${pptStep[1].toLowerCase()}`)
    : command ? t("tool.shell", { command }) : t("tool.shellDefault");

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<CodeOutlined />}
        title={title}
      />
    );
  }

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      icon={<CodeOutlined />}
      title={title}
      content={content}
      isStreaming={isStreaming}
    >
      {pptStep && <DefaultBlock title={t("tool.shellDefault")} content={command} />}
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default ShellCard;
