import React from "react";
import { Button, Card } from "@agentscope-ai/design";
import { ReloadOutlined } from "@ant-design/icons";
import type { MarkdownFile, DailyMemoryFile } from "../../../../api/types";
import { FileItem } from "./FileItem";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface FileListPanelProps {
  files: MarkdownFile[];
  selectedFile: MarkdownFile | null;
  dailyMemories: DailyMemoryFile[];
  expandedMemory: boolean;
  workspacePath: string;
  enabledFiles: string[];
  onRefresh: () => void;
  onFileClick: (file: MarkdownFile) => void;
  onDailyMemoryClick: (daily: DailyMemoryFile) => void;
  onToggleEnabled: (filename: string) => void;
  onReorder: (filename: string, direction: "up" | "down") => void;
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

  // Calculate positions for enabled files
  const getEnabledFilePosition = (filename: string) => {
    const index = enabledFiles.indexOf(filename);
    return {
      isFirst: index === 0,
      isLast: index === enabledFiles.length - 1,
      isEnabled: index !== -1,
    };
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
          <Button size="small" onClick={onRefresh} icon={<ReloadOutlined />}>
            {t("common.refresh")}
          </Button>
        </div>

        <p className={styles.infoText}>{t("workspace.coreFilesDesc")}</p>
        <div className={styles.divider} />

        <div className={styles.scrollContainer}>
          {files.length > 0 ? (
            files.map((file) => {
              const { isFirst, isLast, isEnabled } = getEnabledFilePosition(
                file.filename,
              );
              return (
                <FileItem
                  key={file.filename}
                  file={file}
                  selectedFile={selectedFile}
                  expandedMemory={expandedMemory}
                  dailyMemories={dailyMemories}
                  enabled={isEnabled}
                  isFirst={isFirst}
                  isLast={isLast}
                  onFileClick={onFileClick}
                  onDailyMemoryClick={onDailyMemoryClick}
                  onToggleEnabled={onToggleEnabled}
                  onReorder={onReorder}
                />
              );
            })
          ) : (
            <div className={styles.emptyState}>{t("workspace.noFiles")}</div>
          )}
        </div>
      </Card>
    </div>
  );
};
