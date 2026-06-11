import { useCallback, useEffect, useState } from "react";
import { Drawer, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useArtifactFiles } from "../../hooks/useArtifactFiles";
import { downloadArtifactFile } from "./artifactFileActions";
import ArtifactFilePreviewPanel from "./ArtifactFilePreviewPanel";
import ArtifactFileList from "./ArtifactFileList";
import type { TaskArtifact } from "../../../../api/modules/tasks";
import drawerStyles from "./TaskNodeDrawer.module.less";
import styles from "./ArtifactManageDrawer.module.less";

export interface ArtifactManageDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  userId: string;
  graphId?: string | null;
}

/**
 * 工件管理抽屉 — 文件列表与内联预览与 TaskNodeDrawer「文件」Tab 保持一致。
 */
export default function ArtifactManageDrawer({
  open,
  onClose,
  sessionId,
  userId,
  graphId,
}: ArtifactManageDrawerProps) {
  const { t } = useTranslation();
  const [viewingFile, setViewingFile] = useState<TaskArtifact | null>(null);
  const { files, loading, refresh } = useArtifactFiles({
    sessionId,
    userId,
    graphId,
    enabled: open && !!sessionId,
  });

  useEffect(() => {
    if (!open) {
      setViewingFile(null);
    }
  }, [open]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || !viewingFile) return;
      setViewingFile(null);
    };
    if (open && viewingFile) {
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, viewingFile]);

  const handleDownload = useCallback(
    async (file: TaskArtifact) => {
      try {
        await downloadArtifactFile(file, sessionId, userId);
      } catch (e) {
        console.error("Download failed:", e);
      }
    },
    [sessionId, userId],
  );

  const handleDrawerClose = () => {
    setViewingFile(null);
    onClose();
  };

  return (
    <Drawer
      className={styles.drawer}
      title={null}
      closable={false}
      open={open}
      onClose={handleDrawerClose}
      width={520}
      destroyOnClose
      afterOpenChange={(visible) => {
        if (visible) void refresh();
      }}
    >
      {!viewingFile && (
        <div className={styles.header}>
          <span>{t("taskGraph.artifactManage")}</span>
          <button
            type="button"
            className={styles.closeBtn}
            aria-label={t("taskGraph.close")}
            onClick={handleDrawerClose}
          >
            ×
          </button>
        </div>
      )}

      <div className={styles.body}>
        <div className={drawerStyles.filesTab}>
          {viewingFile ? (
            <ArtifactFilePreviewPanel
              file={viewingFile}
              sessionId={sessionId}
              userId={userId}
              onBack={() => setViewingFile(null)}
            />
          ) : loading ? (
            <div className={drawerStyles.previewLoading}>
              <Spin size="small" />
              <span>{t("taskGraph.previewLoading")}</span>
            </div>
          ) : (
            <ArtifactFileList
              type="ArtifactManage"
              files={files}
              onPreview={setViewingFile}
              onDownload={handleDownload}
              emptyText={t("taskGraph.artifactManageEmpty")}
            />
          )}
        </div>
      </div>
    </Drawer>
  );
}
