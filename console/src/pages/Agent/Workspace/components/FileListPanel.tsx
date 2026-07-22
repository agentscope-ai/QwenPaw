import React from "react";
import { Button, Card } from "@agentscope-ai/design";
import {
  CaretDownOutlined,
  CaretRightOutlined,
  FolderOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import { buildMemoryTree, FileItem } from "./FileItem";
import prettyBytes from "pretty-bytes";
import { formatTimeAgo } from "./utils";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileListPanelProps {
  files: MarkdownFile[];
  selectedFile: MarkdownFile | null;
  dailyMemories: DailyMemoryFile[];
  expandedMemory: boolean;
  workspacePath: string | null;
  enabledFiles: string[];
  onRefresh: () => void;
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onMemoryExpand?: () => void;
  onToggleEnabled: (filename: string) => void;
  onReorder: (newOrder: string[]) => void;
}

export const FileListPanel: React.FC<FileListPanelProps> = ({
  files,
  selectedFile,
  dailyMemories,
  expandedMemory,
  enabledFiles,
  onRefresh,
  onFileClick,
  onDailyMemoryClick,
  onMemoryExpand,
  onToggleEnabled,
  onReorder,
}) => {
  const { t } = useTranslation();
  const [expandedDigestNodes, setExpandedDigestNodes] = React.useState<
    Set<string>
  >(() => new Set());
  const digestRoot = React.useMemo(
    () => buildMemoryTree(dailyMemories).digestRoot,
    [dailyMemories],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 5,
      },
    }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = enabledFiles.indexOf(active.id as string);
    const newIndex = enabledFiles.indexOf(over.id as string);
    if (oldIndex === -1 || newIndex === -1) return;

    const newOrder = arrayMove(enabledFiles, oldIndex, newIndex);
    onReorder(newOrder);
  };

  const isDigestNodeExpanded = (key: string) => expandedDigestNodes.has(key);

  const toggleDigestNode = (key: string) => {
    setExpandedDigestNodes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const renderDigestFile = (
    file: DailyMemoryFile,
    label: string,
    level = 0,
  ) => {
    const isSelected = selectedFile?.memory_path === file.filename;
    return (
      <div
        key={file.filename}
        onClick={() => onDailyMemoryClick(file)}
        className={`${styles.dailyMemoryItem} ${
          isSelected ? styles.selected : ""
        }`}
        style={{ marginLeft: level * 14 }}
      >
        <div className={styles.dailyMemoryName}>{label}</div>
        <div className={styles.dailyMemoryMeta}>
          {prettyBytes(file.size)} · {formatTimeAgo(file.updated_at)}
        </div>
      </div>
    );
  };

  const renderDigestNode = (
    node: typeof digestRoot,
    level = 0,
    path = node.name,
  ): React.ReactNode => {
    if (node.file) {
      return renderDigestFile(node.file, node.name, level);
    }
    const isExpanded = isDigestNodeExpanded(path);
    return (
      <div key={path}>
        <div
          className={`${styles.dailyMemoryItem} ${styles.memoryFolderItem}`}
          style={{ marginLeft: level * 14 }}
          onClick={() => toggleDigestNode(path)}
        >
          {isExpanded ? <CaretDownOutlined /> : <CaretRightOutlined />}
          <FolderOutlined />
          <span>{node.name}</span>
        </div>
        {isExpanded &&
          node.children.map((child) =>
            renderDigestNode(child, level + 1, `${path}/${child.name}`),
          )}
      </div>
    );
  };

  return (
    <div className={styles.fileListPanel}>
      <Card
        bodyStyle={{
          padding: 16,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflow: "auto",
        }}
        style={{ flex: 1, minHeight: 0 }}
      >
        <div className={styles.headerRow}>
          <h3 className={styles.sectionTitle}>{t("workspace.coreFiles")}</h3>
          <Button size="small" onClick={onRefresh} icon={<ReloadOutlined />} />
        </div>

        <p className={styles.infoText}>{t("workspace.coreFilesDesc")}</p>
        <div className={styles.divider} />

        <div className={styles.scrollContainer}>
          {files.length > 0 ? (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={enabledFiles}
                strategy={verticalListSortingStrategy}
              >
                {files.map((file) => {
                  const isEnabled = enabledFiles.includes(file.filename);
                  return (
                    <FileItem
                      key={file.filename}
                      file={file}
                      selectedFile={selectedFile}
                      expandedMemory={expandedMemory}
                      dailyMemories={dailyMemories}
                      enabled={isEnabled}
                      onFileClick={onFileClick}
                      onDailyMemoryClick={onDailyMemoryClick}
                      onMemoryExpand={onMemoryExpand}
                      onToggleEnabled={onToggleEnabled}
                    />
                  );
                })}
              </SortableContext>
            </DndContext>
          ) : (
            <div className={styles.emptyState}>{t("workspace.noFiles")}</div>
          )}
          {digestRoot.children.length > 0 && renderDigestNode(digestRoot)}
        </div>
      </Card>
    </div>
  );
};
