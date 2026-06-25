import React from "react";
import { Switch, Tooltip } from "@agentscope-ai/design";
import {
  CaretDownOutlined,
  CaretRightOutlined,
  FolderOutlined,
  HolderOutlined,
} from "@ant-design/icons";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import prettyBytes from "pretty-bytes";
import { formatTimeAgo } from "./utils";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileItemProps {
  file: MarkdownFile;
  selectedFile: MarkdownFile | null;
  expandedMemory: boolean;
  dailyMemories: DailyMemoryFile[];
  enabled?: boolean;
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onMemoryExpand?: () => void;
  onToggleEnabled: (filename: string) => void;
}

export interface DailyGroup {
  date: string;
  root?: DailyMemoryFile;
  children: DailyMemoryFile[];
}

export interface MemoryTreeNode {
  name: string;
  file?: DailyMemoryFile;
  children: MemoryTreeNode[];
}

const DAILY_ROOT_RE = /^(\d{4}-\d{2}-\d{2})\.md$/;
const DAILY_SESSION_RE = /^(\d{4}-\d{2}-\d{2})\/(.+\.md)$/;

const byModifiedDesc = (a: DailyMemoryFile, b: DailyMemoryFile) =>
  b.updated_at - a.updated_at || a.filename.localeCompare(b.filename);

export const buildMemoryTree = (files: DailyMemoryFile[]) => {
  const dailyGroups = new Map<string, DailyGroup>();
  const miscDaily: DailyMemoryFile[] = [];
  const digestRoot: MemoryTreeNode = {
    name: "digest",
    children: [],
  };

  const ensureDailyGroup = (date: string) => {
    const existing = dailyGroups.get(date);
    if (existing) return existing;
    const created: DailyGroup = { date, children: [] };
    dailyGroups.set(date, created);
    return created;
  };

  const ensureChild = (parent: MemoryTreeNode, name: string) => {
    const existing = parent.children.find((child) => child.name === name);
    if (existing) return existing;
    const child: MemoryTreeNode = { name, children: [] };
    parent.children.push(child);
    return child;
  };

  for (const file of files) {
    if (file.filename.startsWith("digest/")) {
      const parts = file.filename.split("/").slice(1);
      if (parts.length === 0) continue;
      let cursor = digestRoot;
      parts.forEach((part, index) => {
        const child = ensureChild(cursor, part);
        if (index === parts.length - 1) {
          child.file = file;
        }
        cursor = child;
      });
      continue;
    }

    const rootMatch = file.filename.match(DAILY_ROOT_RE);
    if (rootMatch) {
      ensureDailyGroup(rootMatch[1]).root = file;
      continue;
    }

    const sessionMatch = file.filename.match(DAILY_SESSION_RE);
    if (sessionMatch) {
      ensureDailyGroup(sessionMatch[1]).children.push(file);
      continue;
    }

    miscDaily.push(file);
  }

  const daily = Array.from(dailyGroups.values())
    .map((group) => ({
      ...group,
      children: [...group.children].sort(byModifiedDesc),
    }))
    .sort((a, b) => b.date.localeCompare(a.date));

  const sortTree = (node: MemoryTreeNode) => {
    node.children.sort((a, b) => {
      if (Boolean(a.file) !== Boolean(b.file)) {
        return a.file ? 1 : -1;
      }
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sortTree);
  };
  sortTree(digestRoot);

  return {
    daily,
    miscDaily: miscDaily.sort(byModifiedDesc),
    digestRoot,
  };
};

export const FileItem: React.FC<FileItemProps> = ({
  file,
  selectedFile,
  expandedMemory,
  dailyMemories,
  enabled = false,
  onFileClick,
  onDailyMemoryClick,
  onMemoryExpand,
  onToggleEnabled,
}) => {
  const { t } = useTranslation();
  const isSelected = selectedFile?.filename === file.filename;
  const isMemoryFile = file.filename === "MEMORY.md";
  const memoryTree = React.useMemo(
    () => buildMemoryTree(dailyMemories),
    [dailyMemories],
  );
  const [expandedMemoryNodes, setExpandedMemoryNodes] = React.useState<
    Set<string>
  >(() => new Set());

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

  const isMemoryNodeExpanded = (key: string) => expandedMemoryNodes.has(key);

  const toggleMemoryNode = (key: string) => {
    setExpandedMemoryNodes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const renderMemoryFile = (
    memoryFile: DailyMemoryFile,
    label: string,
    level = 0,
    expandKey?: string,
  ) => {
    const isDailySelected = selectedFile?.memory_path === memoryFile.filename;
    const hasChildren = Boolean(expandKey);
    const isExpanded = expandKey ? isMemoryNodeExpanded(expandKey) : false;
    return (
      <div
        key={memoryFile.filename}
        onClick={() => onDailyMemoryClick(memoryFile)}
        className={`${styles.dailyMemoryItem} ${
          isDailySelected ? styles.selected : ""
        }`}
        style={{ marginLeft: level * 14 }}
      >
        <div className={styles.dailyMemoryName}>
          {hasChildren && (
            <button
              type="button"
              className={styles.memoryInlineToggle}
              aria-label={isExpanded ? "collapse" : "expand"}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                if (expandKey) {
                  toggleMemoryNode(expandKey);
                }
              }}
            >
              {isExpanded ? <CaretDownOutlined /> : <CaretRightOutlined />}
            </button>
          )}
          <span>{label}</span>
        </div>
        <div className={styles.dailyMemoryMeta}>
          {prettyBytes(memoryFile.size)} ·{" "}
          {formatTimeAgo(memoryFile.updated_at)}
        </div>
      </div>
    );
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
          {isMemoryFile && (
            <button
              type="button"
              className={styles.expandIcon}
              aria-label={expandedMemory ? "collapse" : "expand"}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onMemoryExpand?.();
              }}
            >
              {expandedMemory ? <CaretDownOutlined /> : <CaretRightOutlined />}
            </button>
          )}
          <div className={styles.fileInfo}>
            <div className={styles.fileItemName}>
              {enabled && <span className={styles.enabledBadge}>●</span>}
              {file.filename}
            </div>
            <div className={styles.fileItemMeta}>
              {prettyBytes(file.size)} · {formatTimeAgo(file.modified_time)}
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

      {isMemoryFile && expandedMemory && (
        <div className={styles.dailyMemoryList}>
          {memoryTree.daily.map((group) => (
            <div key={group.date}>
              {group.root ? (
                renderMemoryFile(
                  group.root,
                  `${group.date}.md`,
                  0,
                  group.children.length > 0 ? `daily/${group.date}` : undefined,
                )
              ) : (
                <div
                  className={`${styles.dailyMemoryItem} ${styles.memoryFolderItem}`}
                  onClick={() => toggleMemoryNode(`daily/${group.date}`)}
                >
                  {isMemoryNodeExpanded(`daily/${group.date}`) ? (
                    <CaretDownOutlined />
                  ) : (
                    <CaretRightOutlined />
                  )}
                  <FolderOutlined />
                  <span>{group.date}</span>
                </div>
              )}
              {isMemoryNodeExpanded(`daily/${group.date}`) &&
                group.children.map((child) =>
                  renderMemoryFile(
                    child,
                    child.filename.split("/").slice(1).join("/"),
                    1,
                  ),
                )}
            </div>
          ))}
          {memoryTree.miscDaily.map((daily) =>
            renderMemoryFile(daily, daily.filename),
          )}
        </div>
      )}
    </div>
  );
};
