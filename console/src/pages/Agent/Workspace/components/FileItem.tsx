import React from "react";
import { Switch, Tooltip } from "@agentscope-ai/design";
import { Checkbox } from "antd";
import {
  CaretDownOutlined,
  CaretRightOutlined,
  HolderOutlined,
} from "@ant-design/icons";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import { formatFileSize, formatTimeAgo } from "./utils";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export interface FileItemProps {
  file: MarkdownFile;
  selectedFile: MarkdownFile | null;
  expandedMemory: boolean;
  dailyMemories: DailyMemoryFile[];
  enabled?: boolean;
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onToggleEnabled: (filename: string) => void;
  viewMode?: "core" | "all";
  selectedForDownload?: boolean;
  onSelectForDownload?: (path: string, selected: boolean) => void;
  /** When true, show rel_path instead of filename (used in search results to distinguish same-name files) */
  showRelPath?: boolean;
  /** When true, renders without dnd-kit useSortable (used in non-sortable contexts for performance) */
  disableDnd?: boolean;
}

/** Shared inner content for both sortable and plain variants */
const FileItemContent: React.FC<
  FileItemProps & {
    isSelected: boolean;
    isDragging?: boolean;
    dragHandleProps?: {
      attributes: React.HTMLAttributes<HTMLElement>;
      listeners: Record<string, unknown> | undefined;
    };
  }
> = ({
  file,
  selectedFile,
  expandedMemory,
  dailyMemories,
  enabled = false,
  onFileClick,
  onDailyMemoryClick,
  onToggleEnabled,
  viewMode = "core",
  selectedForDownload = false,
  onSelectForDownload,
  showRelPath = false,
  isSelected,
  isDragging = false,
  dragHandleProps,
}) => {
  const { t } = useTranslation();
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

  return (
    <>
      <div
        onClick={() => onFileClick(file)}
        className={`${styles.fileItem} ${isSelected ? styles.selected : ""} ${
          isDragging ? styles.dragging : ""
        }`}
      >
        <div className={styles.fileItemHeader}>
          {viewMode === "all" ? (
            <Checkbox
              className={styles.fileCheckbox}
              checked={selectedForDownload}
              onChange={(e) =>
                onSelectForDownload?.(file.path, e.target.checked)
              }
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            enabled &&
            dragHandleProps && (
              <div
                className={styles.dragHandle}
                {...dragHandleProps.attributes}
                {...dragHandleProps.listeners}
                onClick={(e) => e.stopPropagation()}
              >
                <HolderOutlined />
              </div>
            )
          )}
          <div className={styles.fileInfo}>
            <div className={styles.fileItemName}>
              {enabled && <span className={styles.enabledBadge}>鈼?/span>}
              {showRelPath && file.rel_path ? file.rel_path : file.filename}
            </div>
            <div className={styles.fileItemMeta}>
              {formatFileSize(file.size)} 路{" "}
              {formatTimeAgo(file.modified_time || file.updated_at)}
            </div>
          </div>
          <div className={styles.fileItemActions}>
            {viewMode === "core" && (
              <Tooltip title={t("workspace.systemPromptToggleTooltip")}>
                <Switch
                  size="small"
                  checked={enabled}
                  onClick={handleToggleClick}
                />
              </Tooltip>
            )}
            {isMemoryFile && (
              <span className={styles.expandIcon}>
                {expandedMemory ? (
                  <CaretDownOutlined />
                ) : (
                  <CaretRightOutlined />
                )}
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
                  {formatFileSize(daily.size)} 路{" "}
                  {formatTimeAgo(daily.modified_time || daily.updated_at)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
};

/** Sortable variant 鈥?uses useSortable, only for the flat draggable list */
const SortableFileItem: React.FC<FileItemProps> = (props) => {
  const { file, enabled = false } = props;
  const fileId = file.path || file.rel_path || file.filename;
  const selectedId = props.selectedFile
    ? props.selectedFile.path ||
      props.selectedFile.rel_path ||
      props.selectedFile.filename
    : null;
  const isSelected = fileId === selectedId;

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: file.filename, disabled: !enabled });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    position: "relative",
    zIndex: isDragging ? 1 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style}>
      <FileItemContent
        {...props}
        isSelected={isSelected}
        isDragging={isDragging}
        dragHandleProps={{ attributes, listeners }}
      />
    </div>
  );
};

/** Plain (non-sortable) variant 鈥?no dnd-kit hooks, for tree/all/search views */
const PlainFileItem: React.FC<FileItemProps> = (props) => {
  const { file } = props;
  const fileId = file.path || file.rel_path || file.filename;
  const selectedId = props.selectedFile
    ? props.selectedFile.path ||
      props.selectedFile.rel_path ||
      props.selectedFile.filename
    : null;
  const isSelected = fileId === selectedId;

  return (
    <div>
      <FileItemContent {...props} isSelected={isSelected} />
    </div>
  );
};

/**
 * FileItem 鈥?renders as SortableFileItem or PlainFileItem based on disableDnd.
 * Pass disableDnd={true} in any context where sorting is not needed (tree view,
 * all-files view, search results) to avoid expensive useSortable registrations.
 */
export const FileItem: React.FC<FileItemProps> = (props) => {
  if (props.disableDnd) {
    return <PlainFileItem {...props} />;
  }
  return <SortableFileItem {...props} />;
};
