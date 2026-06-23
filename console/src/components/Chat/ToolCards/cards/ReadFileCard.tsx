import React from "react";
import { useTranslation } from "react-i18next";
import { FileTextOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { shortFileName, countLines } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface ReadFileCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ReadFileCard: React.FC<ReadFileCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const file = shortFileName((params.file_path || params.path || "") as string);
  const title = file ? t("tool.readFile", { file }) : t("tool.readFileDefault");

  const resultText = typeof content.result === "string" ? content.result : "";
  const lineCount = countLines(content.result);

  const badge =
    content.status === "done" && lineCount > 0 ? (
      <span className={styles.lineReadBadge}>
        {t("tool.lineBadge.lines", { count: lineCount })}
      </span>
    ) : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<FileTextOutlined />}
      title={title}
      badges={badge}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default ReadFileCard;
