import { useCallback, useEffect, useState } from "react";
import { Drawer, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useArtifactManage } from "../../hooks/useArtifactManage";
import { downloadArtifactFile } from "./artifactFileActions";
import ArtifactFilePreviewPanel from "./ArtifactFilePreviewPanel";
import ArtifactGraphCollapse from "./ArtifactGraphCollapse";
import type { ArtifactFileListItem } from "./ArtifactFileList";
import type { TasksSummaryResponse } from "../../../../api/modules/tasks";
import drawerStyles from "./TaskNodeDrawer.module.less";
import styles from "./ArtifactManageDrawer.module.less";

const SESSION_ARTIFACT_GRAPH_ID = "__session__";

export interface ArtifactManageDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  userId: string;
  /** Graph to expand by default when the drawer opens (does not filter the list). */
  graphId?: string | null;
}

/**
 * 工件管理抽屉 — 按任务图 graph_id 折叠分组，展开时用接口 graph_id 参数懒加载。
 */
export default function ArtifactManageDrawer({
  open,
  onClose,
  sessionId,
  userId,
  graphId,
}: ArtifactManageDrawerProps) {
  const { t } = useTranslation();
  const [viewingFile, setViewingFile] = useState<ArtifactFileListItem | null>(null);
  const [expandedGraphIds, setExpandedGraphIds] = useState<Set<string>>(
    () => new Set(),
  );

  const {
    groups,
    filesByGraph,
    loadingGraphIds,
    indexLoading,
    refreshIndex,
    loadGraphFiles,
    resetLoadedFiles,
  } = useArtifactManage({
    sessionId,
    userId,
    enabled: open && !!sessionId,
  });

  const expandGraph = useCallback(
    (
      targetGraphId: string,
      summaryOverride?: TasksSummaryResponse | null,
    ) => {
      setExpandedGraphIds((prev) => {
        if (prev.has(targetGraphId)) return prev;
        const next = new Set(prev);
        next.add(targetGraphId);
        return next;
      });
      void loadGraphFiles(targetGraphId, { summary: summaryOverride });
    },
    [loadGraphFiles],
  );

  const handleToggleGraph = useCallback(
    (targetGraphId: string) => {
      setExpandedGraphIds((prev) => {
        const next = new Set(prev);
        if (next.has(targetGraphId)) {
          next.delete(targetGraphId);
          return next;
        }
        next.add(targetGraphId);
        void loadGraphFiles(targetGraphId);
        return next;
      });
    },
    [loadGraphFiles],
  );

  const handleDrawerOpen = useCallback(async () => {
    resetLoadedFiles();
    setExpandedGraphIds(new Set());
    const { groups: nextGroups, summary: nextSummary } = await refreshIndex();
    const defaultGraphIds = new Set<string>();
    const sessionGroup = nextGroups.find(
      (group) => group.graphId === SESSION_ARTIFACT_GRAPH_ID,
    );
    if (sessionGroup) {
      defaultGraphIds.add(sessionGroup.graphId);
    }
    if (graphId) {
      defaultGraphIds.add(graphId);
    } else {
      const currentGroup = nextGroups.find((group) => group.isCurrent);
      if (currentGroup) {
        defaultGraphIds.add(currentGroup.graphId);
      }
    }
    defaultGraphIds.forEach((targetGraphId) => {
      expandGraph(targetGraphId, nextSummary);
    });
  }, [expandGraph, graphId, refreshIndex, resetLoadedFiles]);

  useEffect(() => {
    if (!open) {
      setViewingFile(null);
      setExpandedGraphIds(new Set());
      resetLoadedFiles();
    }
  }, [open, resetLoadedFiles]);

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
    async (file: ArtifactFileListItem) => {
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
        if (visible) void handleDrawerOpen();
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
          ) : indexLoading ? (
            <div className={styles.loadingWrap}>
              <Spin size="small" />
              <span>{t("taskGraph.previewLoading")}</span>
            </div>
          ) : (
            <ArtifactGraphCollapse
              groups={groups}
              expandedGraphIds={expandedGraphIds}
              filesByGraph={filesByGraph}
              loadingGraphIds={loadingGraphIds}
              onToggleGraph={handleToggleGraph}
              onPreview={setViewingFile}
              onDownload={handleDownload}
            />
          )}
        </div>
      </div>
    </Drawer>
  );
}
