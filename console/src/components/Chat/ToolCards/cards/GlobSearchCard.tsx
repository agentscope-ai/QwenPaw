import React from "react";
import { useTranslation } from "react-i18next";
import { FolderOpenOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { countLines, stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface GlobSearchCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const GlobSearchCard: React.FC<GlobSearchCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const pattern = (params.pattern || "") as string;
  const title = pattern
    ? t("tool.globSearch", { pattern })
    : t("tool.globSearchDefault");

  const resultText = stringifyResult(content.result);
  const lineCount = countLines(content.result);

  const badge =
    content.status === "done" && lineCount > 0 ? (
      <span className={styles.lineSearchBadge}>
        {t("tool.lineBadge.files", { count: lineCount })}
      </span>
    ) : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<FolderOpenOutlined />}
      title={title}
      badges={badge}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default GlobSearchCard;
