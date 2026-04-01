import React, { useState, useMemo, useTransition } from "react";
import { Button, Card } from "@agentscope-ai/design";
import { Segmented, Checkbox, Input as AntInput, Spin } from "antd";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
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
import { FileItem } from "./FileItem";
import { FolderNode } from "./FolderNode";
import { buildFileTree } from "./utils";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileListPanelProps {
  files: MarkdownFile[];
  selectedFile: MarkdownFile | null;
  dailyMemories: DailyMemoryFile[];
  expandedMemory: boolean;
  workspacePath: string | null;
  enabledFiles: string[];
  viewMode: "core" | "all";
  onViewModeChange: (mode: "core" | "all") => void;
  onRefresh: () => void;
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onToggleEnabled: (filename: string) => void;
  onReorder: (newOrder: string[]) => void;
  onDownloadSelected?: (files: string[]) => void;
  listLoading?: boolean;
}

export const FileListPanel: React.FC<FileListPanelProps> = ({
  files,
  selectedFile,
  dailyMemories,
  expandedMemory,
  workspacePath,
  enabledFiles,
  viewMode,
  onViewModeChange,
  onRefresh,
  onFileClick,
  onDailyMemoryClick,
  onToggleEnabled,
  onReorder,
  onDownloadSelected,
  listLoading = false,
}) => {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedForDownload, setSelectedForDownload] = useState<string[]>([]);

  const [isPending, startTransition] = useTransition();

  const handleViewModeChange = (val: "core" | "all") => {
    startTransition(() => {
      onViewModeChange(val);
    });
  };

  const handleSelectForDownload = (path: string, selected: boolean) => {
    if (selected) {
      setSelectedForDownload((prev) => Array.from(new Set([...prev, path])));
    } else {
      setSelectedForDownload((prev) => prev.filter((p) => p !== path));
    }
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedForDownload(files.map((f) => f.path || f.filename));
    } else {
      setSelectedForDownload([]);
    }
  };

  const isAllSelected =
    files.length > 0 && selectedForDownload.length === files.length;

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

  // Filtered files for search mode
  const filteredFiles = useMemo(() => {
    if (!searchQuery.trim()) return null;
    const q = searchQuery.trim().toLowerCase();
    return files.filter(
      (f) =>
        f.filename.toLowerCase().includes(q) ||
        (f.rel_path || "").toLowerCase().includes(q),
    );
  }, [searchQuery, files]);

  // Tree for non-search mode
  const fileTree = useMemo(
    () => buildFileTree(files, workspacePath),
    [files, workspacePath],
  );

  const hasSubfolders =
    fileTree.children.length > 0 || fileTree.files.length !== files.length;

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
          <h3 className={styles.sectionTitle}>
            {viewMode === "core"
              ? t("workspace.coreFiles")
              : t("workspace.allFiles", "All Files")}
          </h3>
          <Button size="small" onClick={onRefresh} icon={<ReloadOutlined />} />

        </div>

        <Segmented
          options={[
            { label: t("workspace.coreFiles"), value: "core" },
            { label: t("workspace.allFiles", "All Files"), value: "all" },
          ]}
          value={viewMode}
          onChange={(val) => handleViewModeChange(val as "core" | "all")}
          style={{ marginBottom: 12 }}
          block
        />

        {viewMode === "core" && (
          <p className={styles.infoText}>{t("workspace.coreFilesDesc")}</p>
        )}

        {viewMode === "all" && (
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <Checkbox
              checked={isAllSelected}
              onChange={(e) => handleSelectAll(e.target.checked)}
            >
              Select All
            </Checkbox>
            <Button
              size="small"
              type="primary"
              disabled={selectedForDownload.length === 0}
              onClick={() => onDownloadSelected?.(selectedForDownload)}
            >
              Download ({selectedForDownload.length})
            </Button>
          </div>
        )}

        {/* Search box */}
        <AntInput
          prefix={<SearchOutlined style={{ color: "#bbb" }} />}
          placeholder={t("workspace.searchPlaceholder", "Search files…")}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
          size="small"
          className={styles.searchInput}
        />

        <div className={styles.divider} />

        <div className={styles.scrollContainer}>
          {(listLoading || isPending) ? (
            <div style={{ display: "flex", justifyContent: "center", paddingTop: 32 }}>
              <Spin />
            </div>
          ) : files.length === 0 ? (
            <div className={styles.emptyState}>{t("workspace.noFiles")}</div>
          ) : filteredFiles !== null ? (
            /* ── Search results: flat list ── */
            filteredFiles.length === 0 ? (
              <div className={styles.emptyState}>
                {t("workspace.noSearchResults", "No files match your search")}
              </div>
            ) : (
              filteredFiles.map((file) => (
                <FileItem
                  key={file.path || file.rel_path || file.filename}
                  file={file}
                  selectedFile={selectedFile}
                  expandedMemory={false}
                  dailyMemories={[]}
                  enabled={enabledFiles.includes(file.filename)}
                  onFileClick={onFileClick}
                  onDailyMemoryClick={onDailyMemoryClick}
                  onToggleEnabled={onToggleEnabled}
                  viewMode={viewMode}
                  showRelPath
                  disableDnd
                  selectedForDownload={selectedForDownload.includes(
                    file.path || file.filename,
                  )}
                  onSelectForDownload={handleSelectForDownload}
                />
              ))
            )
          ) : hasSubfolders ? (
            /* ── Tree view when subfolders exist ── */
            <>
              {fileTree.files.map((file) => (
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
                  selectedForDownload={selectedForDownload.includes(
                    file.path || file.filename,
                  )}
                  onSelectForDownload={handleSelectForDownload}
                />
              ))}
              {fileTree.children.map((node) => (
                <FolderNode
                  key={node.id}
                  node={node}
                  depth={0}
                  selectedFile={selectedFile}
                  expandedMemory={expandedMemory}
                  dailyMemories={dailyMemories}
                  enabledFiles={enabledFiles}
                  onFileClick={onFileClick}
                  onDailyMemoryClick={onDailyMemoryClick}
                  onToggleEnabled={onToggleEnabled}
                  viewMode={viewMode}
                  selectedForDownload={selectedForDownload}
                  onSelectForDownload={handleSelectForDownload}
                />
              ))}
            </>
          ) : (
            /* ── Flat sortable list (core mode, no subfolders) ── */
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
                      key={file.path || file.rel_path || file.filename}
                      file={file}
                      selectedFile={selectedFile}
                      expandedMemory={expandedMemory}
                      dailyMemories={dailyMemories}
                      enabled={isEnabled}
                      onFileClick={onFileClick}
                      onDailyMemoryClick={onDailyMemoryClick}
                      onToggleEnabled={onToggleEnabled}
                      viewMode={viewMode}
                      selectedForDownload={selectedForDownload.includes(
                        file.path || file.filename,
                      )}
                      onSelectForDownload={handleSelectForDownload}
                    />
                  );
                })}
              </SortableContext>
            </DndContext>
          )}
        </div>
      </Card>
    </div>
  );
};
