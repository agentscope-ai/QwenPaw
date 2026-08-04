import React, { useMemo, useState } from "react";
import { Drawer } from "antd";
import { invoke } from "@tauri-apps/api/core";
import {
  Download,
  Eye,
  FileArchive,
  FileText,
  FolderSearch,
  ListTree,
  SquareArrowOutUpRight,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { buildAuthHeaders } from "../../../../api/authHeaders";
import { workspaceApi } from "../../../../api/modules/workspace";
import FilePreview from "../../../../pages/Coding/FilePreview";
import { downloadFileFromUrl } from "../../../../utils/downloadFileFromUrl";
import { isTauriRuntime } from "../../../../tauri/backendRuntime";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import type { ArtifactEntry } from "./workspaceArtifacts";
import { parseManifest } from "./workspaceArtifacts";
import styles from "./workspaceArtifacts.module.less";

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function isInlinePreview(artifact: ArtifactEntry): boolean {
  return ["image", "pdf", "markdown", "csv", "text"].includes(artifact.preview);
}

const WorkspaceArtifactsCard: React.FC<{
  content: ToolCallContent;
  isStreaming?: boolean;
}> = ({ content, isStreaming }) => {
  const { t } = useTranslation();
  const [drawer, setDrawer] = useState<
    "artifacts" | "changes" | "preview" | null
  >(null);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactEntry | null>(
    null,
  );
  const [previewContent, setPreviewContent] = useState("");
  const manifest = useMemo(
    () => parseManifest(content.result),
    [content.result],
  );
  const artifacts = manifest?.artifacts ?? [];
  const desktop = isTauriRuntime();
  const title = t("tool.workspaceArtifacts", "Workspace artifacts");

  const downloadArtifact = (artifact: ArtifactEntry) => {
    if (!manifest) return;
    void downloadFileFromUrl(
      workspaceApi.getArtifactFileUrl(manifest.agent_id, artifact.path),
      artifact.name,
      { errorMessage: "Artifact download failed" },
    );
  };

  const openPreview = async (artifact: ArtifactEntry) => {
    if (!manifest) return;
    setPreviewArtifact(artifact);
    setPreviewContent("");
    setDrawer("preview");
    if (["markdown", "csv", "text"].includes(artifact.preview)) {
      const response = await fetch(
        workspaceApi.getArtifactFileUrl(manifest.agent_id, artifact.path),
        { headers: buildAuthHeaders() },
      );
      if (response.ok) setPreviewContent(await response.text());
    }
  };

  const invokeArtifactCommand = (
    command: "open_workspace_artifact" | "reveal_workspace_artifact",
    artifact: ArtifactEntry,
  ) => {
    if (!manifest) return;
    void invoke(command, {
      agentId: manifest.agent_id,
      filePath: artifact.path,
    });
  };

  const renderArtifact = (artifact: ArtifactEntry) => (
    <div className={styles.artifactRow} key={artifact.path}>
      <FileText className={styles.fileIcon} size={17} aria-hidden="true" />
      <span className={styles.fileIdentity}>
        <span className={styles.fileName} title={artifact.path}>
          {artifact.name}
        </span>
        <span className={styles.fileMeta}>
          {artifact.extension || artifact.mime_type} ·{" "}
          {formatSize(artifact.size)}
        </span>
      </span>
      <span className={styles.changeBadge}>{artifact.change}</span>
      <span>
        {isInlinePreview(artifact) && (
          <button
            className={styles.iconButton}
            type="button"
            aria-label={`Preview ${artifact.name}`}
            onClick={() => void openPreview(artifact)}
          >
            <Eye size={15} aria-hidden="true" />
          </button>
        )}
        <button
          className={styles.iconButton}
          type="button"
          aria-label={`Download ${artifact.name}`}
          onClick={() => downloadArtifact(artifact)}
        >
          <Download size={15} aria-hidden="true" />
        </button>
        {desktop && (
          <>
            <button
              className={styles.iconButton}
              type="button"
              aria-label={`Open ${artifact.name}`}
              onClick={() =>
                invokeArtifactCommand("open_workspace_artifact", artifact)
              }
            >
              <SquareArrowOutUpRight size={15} aria-hidden="true" />
            </button>
            <button
              className={styles.iconButton}
              type="button"
              aria-label={`Reveal ${artifact.name}`}
              onClick={() =>
                invokeArtifactCommand("reveal_workspace_artifact", artifact)
              }
            >
              <FolderSearch size={15} aria-hidden="true" />
            </button>
          </>
        )}
      </span>
    </div>
  );

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<FileArchive size={16} aria-hidden="true" />}
      title={title}
      badges={manifest ? <span>{artifacts.length}</span> : undefined}
    >
      {manifest ? (
        <div className={styles.artifactCard}>
          <div className={styles.artifactList}>
            {artifacts.slice(0, 4).map(renderArtifact)}
          </div>
          <div className={styles.footerActions}>
            <button
              className={styles.textButton}
              type="button"
              onClick={() => setDrawer("artifacts")}
            >
              <FileArchive size={15} aria-hidden="true" />
              {t("tool.workspaceArtifactsViewAll", "View all artifacts")}
            </button>
            <button
              className={styles.textButton}
              type="button"
              onClick={() => setDrawer("changes")}
            >
              <ListTree size={15} aria-hidden="true" />
              {t("tool.workspaceArtifactsViewChanges", "View all changes")}
            </button>
          </div>
          {manifest.truncated && (
            <span className={styles.fileMeta}>
              {t("tool.workspaceArtifactsTruncated", "More files available")}
            </span>
          )}
        </div>
      ) : (
        <div className={styles.emptyState}>
          {t(
            "tool.workspaceArtifactsUnavailable",
            "Artifact details unavailable",
          )}
        </div>
      )}
      {manifest && (
        <Drawer
          open={drawer !== null}
          onClose={() => setDrawer(null)}
          width={560}
          title={
            drawer === "changes"
              ? t("tool.workspaceArtifactsChanges", "Workspace changes")
              : previewArtifact?.name || title
          }
        >
          {drawer === "artifacts" && (
            <div className={styles.drawerBody}>
              {artifacts.map(renderArtifact)}
            </div>
          )}
          {drawer === "changes" && (
            <div className={styles.drawerBody}>
              {manifest.changes.map((change) => (
                <div className={styles.artifactRow} key={change.path}>
                  <ListTree size={16} aria-hidden="true" />
                  <span className={styles.fileName}>{change.path}</span>
                  <span className={styles.changeBadge}>{change.change}</span>
                </div>
              ))}
            </div>
          )}
          {drawer === "preview" && previewArtifact && (
            <div className={styles.previewBody}>
              <FilePreview
                filePath={previewArtifact.path}
                content={previewContent}
                artifactAgentId={manifest.agent_id}
              />
            </div>
          )}
        </Drawer>
      )}
    </ToolCardShell>
  );
};

export default WorkspaceArtifactsCard;
