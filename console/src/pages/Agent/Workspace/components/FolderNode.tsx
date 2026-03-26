import React, { useState } from "react";
import {
  CaretRightOutlined,
  FolderOutlined,
  FolderOpenOutlined,
} from "@ant-design/icons";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import type { FileTreeNode } from "./utils";
import { FileItem } from "./FileItem";
import styles from "../index.module.less";

// ---------------------------------------------------------------------------
// FolderRowItem — lightweight single-row component used by the virtual list
// (all mode). Only renders the folder header; children are managed by the
// virtual list itself via flattenTree.
// ---------------------------------------------------------------------------
interface FolderRowItemProps {
  node: FileTreeNode;
  depth: number;
  expanded: boolean;
  onToggle: () => void;
}

export const FolderRowItem: React.FC<FolderRowItemProps> = ({
  node,
  depth,
  expanded,
  onToggle,
}) => {
  return (
    <div
      className={styles.folderNode}
      style={{ marginLeft: depth > 0 ? depth * 12 : 0 }}
    >
      <div
        className={styles.folderRow}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && onToggle()}
      >
        <span
          className={`${styles.folderChevron} ${
            expanded ? styles.folderChevronOpen : ""
          }`}
        >
          <CaretRightOutlined />
        </span>
        <span className={styles.folderIcon}>
          {expanded ? <FolderOpenOutlined /> : <FolderOutlined />}
        </span>
        <span className={styles.folderName}>{node.name}</span>
      </div>
    </div>
  );
};

interface FolderNodeProps {
  node: FileTreeNode;
  depth: number;
  selectedFile: MarkdownFile | null;
  expandedMemory: boolean;
  dailyMemories: DailyMemoryFile[];
  enabledFiles: string[];
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onToggleEnabled: (filename: string) => void;
  viewMode?: "core" | "all";
  selectedForDownload?: string[];
  onSelectForDownload?: (path: string, selected: boolean) => void;
}

export const FolderNode: React.FC<FolderNodeProps> = ({
  node,
  depth,
  selectedFile,
  expandedMemory,
  dailyMemories,
  enabledFiles,
  onFileClick,
  onDailyMemoryClick,
  onToggleEnabled,
  viewMode = "core",
  selectedForDownload = [],
  onSelectForDownload,
}) => {
  const [open, setOpen] = useState(false);

  const totalFiles =
    node.files.length +
    node.children.reduce((sum, c) => sum + c.files.length, 0);

  return (
    <div
      className={styles.folderNode}
      style={{ marginLeft: depth > 0 ? 12 : 0 }}
    >
      {/* Folder header row */}
      <div
        className={styles.folderRow}
        onClick={() => setOpen((v) => !v)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && setOpen((v) => !v)}
      >
        <span
          className={`${styles.folderChevron} ${
            open ? styles.folderChevronOpen : ""
          }`}
        >
          <CaretRightOutlined />
        </span>
        <span className={styles.folderIcon}>
          {open ? <FolderOpenOutlined /> : <FolderOutlined />}
        </span>
        <span className={styles.folderName}>{node.name}</span>
        <span className={styles.folderCount}>{totalFiles}</span>
      </div>

      {/* Folder children */}
      {open && (
        <div className={styles.folderChildren}>
          {/* Direct files inside this folder */}
          {node.files.map((file) => (
            <FileItem
              key={file.path || file.rel_path || file.filename}
              file={file}
              selectedFile={selectedFile}
              expandedMemory={expandedMemory}
              dailyMemories={dailyMemories}
              enabled={enabledFiles.includes(file.filename)}
              onFileClick={onFileClick}
              onDailyMemoryClick={onDailyMemoryClick}
              onToggleEnabled={onToggleEnabled}
              viewMode={viewMode}
              disableDnd
              selectedForDownload={selectedForDownload.includes(file.path)}
              onSelectForDownload={onSelectForDownload}
            />
          ))}

          {/* Sub-folders */}
          {node.children.map((child) => (
            <FolderNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedFile={selectedFile}
              expandedMemory={expandedMemory}
              dailyMemories={dailyMemories}
              enabledFiles={enabledFiles}
              onFileClick={onFileClick}
              onDailyMemoryClick={onDailyMemoryClick}
              onToggleEnabled={onToggleEnabled}
              viewMode={viewMode}
              selectedForDownload={selectedForDownload}
              onSelectForDownload={onSelectForDownload}
            />
          ))}
        </div>
      )}
    </div>
  );
};
