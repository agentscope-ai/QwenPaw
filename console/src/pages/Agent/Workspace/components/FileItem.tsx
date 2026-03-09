import React from "react";
import { Switch, Tooltip, Button } from "@agentscope-ai/design";
import { UpOutlined, DownOutlined } from "@ant-design/icons";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import { formatFileSize, formatTimeAgo } from "./utils";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileItemProps {
  file: MarkdownFile;
  selectedFile: MarkdownFile | null;
  expandedMemory: boolean;
  dailyMemories: DailyMemoryFile[];
  enabled?: boolean;
  isFirst?: boolean;
  isLast?: boolean;
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onToggleEnabled: (filename: string) => void;
  onReorder?: (filename: string, direction: "up" | "down") => void;
}

export const FileItem: React.FC<FileItemProps> = ({
  file,
  selectedFile,
  expandedMemory,
  dailyMemories,
  enabled = false,
  isFirst = false,
  isLast = false,
  onFileClick,
  onDailyMemoryClick,
  onToggleEnabled,
  onReorder,
}) => {
  const { t } = useTranslation();
  const isSelected = selectedFile?.filename === file.filename;
  const isMemoryFile = file.filename === "MEMORY.md";

  const handleToggleClick = (
    _checked: boolean,
    event:
      | React.MouseEvent<HTMLButtonElement>
      | React.KeyboardEvent<HTMLButtonElement>,
  ) => {
    event.stopPropagation();
    onToggleEnabled(file.filename);
  };

  const handleReorderClick = (
    e: React.MouseEvent,
    direction: "up" | "down",
  ) => {
    e.stopPropagation();
    if (onReorder) {
      onReorder(file.filename, direction);
    }
  };

  return (
    <div>
      <div
        onClick={() => onFileClick(file)}
        className={`${styles.fileItem} ${isSelected ? styles.selected : ""}`}
      >
        <div className={styles.fileItemHeader}>
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
            {enabled && onReorder && (
              <div className={styles.reorderButtons}>
                <Button
                  type="text"
                  size="small"
                  icon={<UpOutlined />}
                  disabled={isFirst}
                  onClick={(e) => handleReorderClick(e, "up")}
                  className={styles.reorderButton}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<DownOutlined />}
                  disabled={isLast}
                  onClick={(e) => handleReorderClick(e, "down")}
                  className={styles.reorderButton}
                />
              </div>
            )}
            <Tooltip title={t("workspace.systemPromptToggleTooltip")}>
              <Switch
                size="small"
                checked={enabled}
                onClick={handleToggleClick}
              />
            </Tooltip>
            {isMemoryFile && (
              <span className={styles.expandIcon}>
                {expandedMemory ? "▼" : "▶"}
              </span>
            )}
          </div>
        </div>
      </div>

      {isMemoryFile && expandedMemory && (
        <div className={styles.dailyMemoryList}>
          {dailyMemories.map((daily) => {
            const isDailySelected =
              selectedFile?.filename === `${daily.date}.md`;
            return (
              <div
                key={daily.date}
                onClick={() => onDailyMemoryClick(daily)}
                className={`${styles.dailyMemoryItem} ${
                  isDailySelected ? styles.selected : ""
                }`}
              >
                <div className={styles.dailyMemoryName}>{daily.date}.md</div>
                <div className={styles.dailyMemoryMeta}>
                  {formatFileSize(daily.size)} ·{" "}
                  {formatTimeAgo(daily.updated_at)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
