/**
 * GenericToolCard — fallback card for tool calls not in the builtin registry.
 *
 * Shows the tool name + spinner while no output is available,
 * then a collapsible result block once the tool completes.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { ToolOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { DefaultBlock } from "../shared";
import InlineMediaText from "../shared/InlineMediaText";
import { extractAllMediaFromResult, stringifyResult } from "../shared/utils";

export interface GenericToolCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const GenericToolCard: React.FC<GenericToolCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const toolLabel = content.serverLabel
    ? `${content.serverLabel} / ${content.name}`
    : content.name;
  const resultText = stringifyResult(content.result);
  const mediaList = extractAllMediaFromResult(content);
  const hasOutput = resultText || mediaList.length > 0;

  return (
    <ToolCardShell
      icon={<ToolOutlined />}
      title={t("tool.execute", { tool: toolLabel })}
      content={content}
      isStreaming={isStreaming}
      disableAutoMedia
    >
      {(isOpen) =>
        hasOutput && (
          <DefaultBlock
            title="Output"
            content={resultText}
            renderContent={
              isOpen && mediaList.length > 0
                ? () => <InlineMediaText text={resultText} media={mediaList} />
                : undefined
            }
          />
        )
      }
    </ToolCardShell>
  );
};

export default GenericToolCard;
