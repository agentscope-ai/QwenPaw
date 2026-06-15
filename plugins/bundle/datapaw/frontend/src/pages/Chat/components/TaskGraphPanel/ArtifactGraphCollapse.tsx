import { useTranslation } from "react-i18next";
import { Spin } from "antd";
import type { ArtifactGraphGroup } from "../../hooks/useArtifactManage";
import type { TaskArtifact } from "../../../../api/modules/tasks";
import ArtifactFileList, { type ArtifactFileListItem } from "./ArtifactFileList";
import styles from "./ArtifactManageDrawer.module.less";

export interface ArtifactGraphCollapseProps {
  groups: ArtifactGraphGroup[];
  expandedGraphIds: Set<string>;
  filesByGraph: Record<string, TaskArtifact[]>;
  loadingGraphIds: Set<string>;
  onToggleGraph: (graphId: string) => void;
  onPreview: (file: ArtifactFileListItem) => void;
  onDownload: (file: ArtifactFileListItem) => void;
}

export default function ArtifactGraphCollapse({
  groups,
  expandedGraphIds,
  filesByGraph,
  loadingGraphIds,
  onToggleGraph,
  onPreview,
  onDownload,
}: ArtifactGraphCollapseProps) {
  const { t } = useTranslation();

  if (groups.length === 0) {
    return (
      <div className={styles.empty}>
        {t("taskGraph.artifactManageEmpty")}
      </div>
    );
  }

  return (
    <div className={styles.graphCollapse}>
      {groups.map((group) => {
        const expanded = expandedGraphIds.has(group.graphId);
        const loading = loadingGraphIds.has(group.graphId);
        const files = filesByGraph[group.graphId] ?? [];

        return (
          <section key={group.graphId} className={styles.graphGroup}>
            <button
              type="button"
              className={styles.graphHeader}
              aria-expanded={expanded}
              onClick={() => onToggleGraph(group.graphId)}
            >
              <span className={styles.chevron} aria-hidden>
                {expanded ? "▾" : "▸"}
              </span>
              <span className={styles.graphTitle} title={group.name}>
                {group.name}
              </span>
              {group.isCurrent ? (
                <span className={styles.currentBadge}>
                  {t("taskGraph.artifactGraphCurrent")}
                </span>
              ) : null}
              <span className={styles.fileCountBadge}>
                {t("taskGraph.artifactGraphFiles", { count: group.fileCount })}
              </span>
            </button>

            {expanded ? (
              <div className={styles.graphBody}>
                {loading ? (
                  <div className={styles.groupLoading}>
                    <Spin size="small" />
                    <span>{t("taskGraph.previewLoading")}</span>
                  </div>
                ) : (
                  <ArtifactFileList
                    type="ArtifactManage"
                    files={files}
                    onPreview={onPreview}
                    onDownload={onDownload}
                    emptyText={t("taskGraph.artifactGraphEmpty")}
                  />
                )}
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
