import React from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { RefreshCw } from "lucide-react";
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
  onToggleEnabled,
  onReorder,
}) => {
  const { t } = useTranslation();

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

  return (
    <div className={styles.fileListPanel}>
      <Card style={{ flex: 1, minHeight: 0 }}>
        <CardContent
          style={{
            padding: 16,
            display: "flex",
            flexDirection: "column",
            height: "100%",
            overflow: "auto",
          }}
        >
          <div className={styles.headerRow}>
            <h3 className={styles.sectionTitle}>{t("workspace.coreFiles")}</h3>
            <Button size="sm" variant="outline" onClick={onRefresh}>
              <RefreshCw size={14} />
            </Button>
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
                        onToggleEnabled={onToggleEnabled}
                      />
                    );
                  })}
                </SortableContext>
              </DndContext>
            ) : (
              <div className={styles.emptyState}>{t("workspace.noFiles")}</div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
