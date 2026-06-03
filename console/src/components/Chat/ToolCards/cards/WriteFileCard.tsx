import React from "react";
import { useTranslation } from "react-i18next";
import { FileAddOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { shortFileName, countLines, getFileLanguage } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface WriteFileCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const WriteFileCard: React.FC<WriteFileCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const file = shortFileName((params.file_path || params.path || "") as string);
  const title = file
    ? t("tool.writeFile", { file })
    : t("tool.writeFileDefault");

  const writtenContent = (params.content as string) || "";
  const lineCount = countLines(writtenContent);
  const lang = getFileLanguage(content);

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
      {writtenContent && (
        <div className={styles.toolCallResultMd}>
          <Markdown content={`\`\`\`${lang}\n${writtenContent}\n\`\`\``} />
        </div>
      )}
    </ToolCardShell>
  );
};

export default WriteFileCard;
