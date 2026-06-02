import React from "react";
import { useTranslation } from "react-i18next";
import { SearchOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { countLines, stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface GrepSearchCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const GrepSearchCard: React.FC<GrepSearchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const pattern = (params.pattern || "") as string;
  const title = pattern
    ? t("tool.grepSearch", { pattern })
    : t("tool.grepSearchDefault");

  const resultText = stringifyResult(content.result);
  const lineCount = countLines(content.result);

  const badge =
    content.status === "done" && lineCount > 0 ? (
      <span className={styles.lineSearchBadge}>
        {t("tool.lineBadge.matches", { count: lineCount })}
      </span>
    ) : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<SearchOutlined />}
      title={title}
      badges={badge}
    >
      {resultText && (
        <div className={styles.toolCallResultMd}>
          <Markdown content={`\`\`\`\n${resultText}\n\`\`\``} />
        </div>
      )}
    </ToolCardShell>
  );
};

export default GrepSearchCard;
