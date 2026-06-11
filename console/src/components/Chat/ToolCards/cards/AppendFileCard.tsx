import React from "react";
import { useTranslation } from "react-i18next";
import { FileAddOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { shortFileName, countLines } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface AppendFileCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const AppendFileCard: React.FC<AppendFileCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const file = shortFileName((params.file_path || params.path || "") as string);
  const title = file
    ? t("tool.appendFile", { file })
    : t("tool.appendFileDefault");

  const appendedContent = (params.content as string) || "";
  const lineCount = countLines(appendedContent);

  const badge =
    !content.status?.startsWith("call") && lineCount > 0 ? (
      <span className={styles.diffAddBadge}>
        {t("tool.lineBadge.lines", { count: lineCount })}
      </span>
    ) : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<FileAddOutlined />}
      title={title}
      badges={badge}
    >
      {appendedContent && (
        <DefaultBlock title="Content" content={appendedContent} />
      )}
    </ToolCardShell>
  );
};

export default AppendFileCard;
