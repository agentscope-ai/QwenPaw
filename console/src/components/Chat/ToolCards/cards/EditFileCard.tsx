import React from "react";
import { useTranslation } from "react-i18next";
import { EditOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { shortFileName } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface EditFileCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const EditFileCard: React.FC<EditFileCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const file = shortFileName((params.file_path || params.path || "") as string);
  const title = file ? t("tool.editFile", { file }) : t("tool.editFileDefault");

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<EditOutlined />}
        title={title}
      />
    );
  }

  const oldText = (params.old_text as string) || "";
  const newText = (params.new_text as string) || "";
  const isLoading = content.status === "calling" && isStreaming;

  const badges = !isLoading ? (
    <>
      <span className={styles.diffAddBadge}>
        {t("tool.lineBadge.addLines", {
          count: newText.split("\n").length,
        })}
      </span>
      <span className={styles.diffDelBadge}>
        {t("tool.lineBadge.delLines", {
          count: oldText.split("\n").length,
        })}
      </span>
    </>
  ) : null;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<EditOutlined />}
      title={title}
      badges={badges}
    >
      {params && (
        <div className={styles.toolCallDiff}>
          {oldText.split("\n").map((line, index) => (
            <div key={`d${index}`} className={styles.diffLineDel}>
              - {line}
            </div>
          ))}
          {newText.split("\n").map((line, index) => (
            <div key={`a${index}`} className={styles.diffLineAdd}>
              + {line}
            </div>
          ))}
        </div>
      )}
    </ToolCardShell>
  );
};

export default EditFileCard;
