import React from "react";
import { Switch, Tooltip } from "@agentscope-ai/design";
import { HolderOutlined } from "@ant-design/icons";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { MarkdownFile } from "../../../../api/types";
import { formatFileSize, formatTimeAgo } from "./utils";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileItemProps {
  file: MarkdownFile;
  selectedFile: MarkdownFile | null;
  enabled?: boolean;
  onFileClick: (file: MarkdownFile) => void;
  onToggleEnabled: (filename: string) => void;
}

export const FileItem: React.FC<FileItemProps> = ({
  file,
  selectedFile,
  enabled = false,
  onFileClick,
  onToggleEnabled,
}) => {
  const { t } = useTranslation();
  const isSelected = selectedFile?.filename === file.filename;

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: file.filename,
    disabled: !enabled,
  });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: "relative",
    zIndex: isDragging ? 1 : undefined,
  };

  const handleToggleClick = (
    _checked: boolean,
    event:
      | React.MouseEvent<HTMLButtonElement>
      | React.KeyboardEvent<HTMLButtonElement>,
  ) => {
    event.stopPropagation();
    onToggleEnabled(file.filename);
  };

  return (
    <div ref={setNodeRef} style={style}>
      <div
        onClick={() => onFileClick(file)}
        className={`${styles.fileItem} ${isSelected ? styles.selected : ""} ${
          isDragging ? styles.dragging : ""
        }`}
      >
        <div className={styles.fileItemHeader}>
          {enabled && (
            <div
              className={styles.dragHandle}
              {...attributes}
              {...listeners}
              onClick={(e) => e.stopPropagation()}
            >
              <HolderOutlined />
            </div>
          )}
          <div className={styles.fileInfo}>
            <div className={styles.fileItemName}>
              {enabled && <span className={styles.enabledBadge}>●</span>}
              {file.filename}
            </div>
            <div className={styles.fileItemMeta}>
              {formatFileSize(file.size)} · {formatTimeAgo(file.updated_at)}
            </div>
          </div>
          <div className={styles.fileItemActions}>
            <Tooltip title={t("workspace.systemPromptToggleTooltip")}>
              <Switch
                size="small"
                checked={enabled}
                onClick={handleToggleClick}
              />
            </Tooltip>
          </div>
        </div>
      </div>
    </div>
  );
};
