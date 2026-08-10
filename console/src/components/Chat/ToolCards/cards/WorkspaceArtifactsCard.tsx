import React, { useEffect, useMemo, useRef, useState } from "react";
import { Drawer, Spin } from "antd";
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
import { useAppMessage } from "../../../../hooks/useAppMessage";
import FilePreview from "../../../../pages/Coding/FilePreview";
import {
  DownloadCancelledError,
  downloadFileFromUrl,
} from "../../../../utils/downloadFileFromUrl";
import { isTauriRuntime } from "../../../../tauri/backendRuntime";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import type { ArtifactEntry } from "./workspaceArtifacts";
import { parseManifest } from "./workspaceArtifacts";
import {
  ARTIFACT_TEXT_PREVIEW_MAX_BYTES,
  getArtifactPreviewLimit,
} from "../../../../types/workspaceArtifacts";
import styles from "./workspaceArtifacts.module.less";

class PreviewTooLargeError extends Error {}

async function readPreviewText(
  response: Response,
  maxBytes: number,
): Promise<string> {
  const declaredSize = Number(response.headers?.get("Content-Length"));
  if (Number.isFinite(declaredSize) && declaredSize > maxBytes) {
    throw new PreviewTooLargeError();
  }
  if (!response.body) {
    const text = await response.text();
    if (new TextEncoder().encode(text).byteLength > maxBytes) {
      throw new PreviewTooLargeError();
    }
    return text;
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > maxBytes) {
      await reader.cancel();
      throw new PreviewTooLargeError();
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

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
  const { message } = useAppMessage();
  const [drawer, setDrawer] = useState<
    "artifacts" | "changes" | "preview" | null
  >(null);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactEntry | null>(
    null,
  );
  const [previewContent, setPreviewContent] = useState("");
  const [previewStatus, setPreviewStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [previewError, setPreviewError] = useState<"failed" | "too_large">(
    "failed",
  );
  const previewRequestId = useRef(0);
  const previewAbortController = useRef<AbortController | null>(null);
  const manifest = useMemo(
    () => parseManifest(content.result),
    [content.result],
  );
  const artifacts = manifest?.artifacts ?? [];
  const desktop = isTauriRuntime();
  const title = t("tool.workspaceArtifacts", "Workspace artifacts");

  useEffect(
    () => () => {
      previewAbortController.current?.abort();
    },
    [],
  );

  const downloadArtifact = async (artifact: ArtifactEntry) => {
    if (!manifest) return;
    try {
      await downloadFileFromUrl(
        workspaceApi.getArtifactFileUrl(
          manifest.agent_id,
          artifact.path,
          artifact.root,
          artifact.root_ref,
        ),
        artifact.name,
        {
          headers: {
            ...buildAuthHeaders(),
            "X-Chat-Id": manifest.chat_id,
          },
          errorMessage: "Artifact download failed",
        },
      );
    } catch (error) {
      if (error instanceof DownloadCancelledError) return;
      message.error(
        t("tool.workspaceArtifactDownloadFailed", "Artifact download failed"),
      );
    }
  };

  const openPreview = async (artifact: ArtifactEntry) => {
    if (!manifest) return;
    const requestId = previewRequestId.current + 1;
    previewRequestId.current = requestId;
    previewAbortController.current?.abort();
    previewAbortController.current = null;
    setPreviewArtifact(artifact);
    setPreviewContent("");
    setDrawer("preview");
    setPreviewError("failed");
    const previewLimit = getArtifactPreviewLimit(artifact.preview);
    if (previewLimit !== null && artifact.size > previewLimit) {
      setPreviewError("too_large");
      setPreviewStatus("error");
      return;
    }
    if (["markdown", "csv", "text"].includes(artifact.preview)) {
      const controller = new AbortController();
      previewAbortController.current = controller;
      setPreviewStatus("loading");
      try {
        const response = await fetch(
          workspaceApi.getArtifactPreviewUrl(
            manifest.agent_id,
            artifact.path,
            artifact.root,
            artifact.root_ref,
          ),
          {
            headers: {
              ...buildAuthHeaders(),
              "X-Chat-Id": manifest.chat_id,
            },
            signal: controller.signal,
          },
        );
        if (!response.ok) {
          if (response.status === 413) throw new PreviewTooLargeError();
          throw new Error(`Preview failed: ${response.status}`);
        }
        const text = await readPreviewText(
          response,
          previewLimit ?? ARTIFACT_TEXT_PREVIEW_MAX_BYTES,
        );
        if (previewRequestId.current !== requestId) return;
        setPreviewContent(text);
        setPreviewStatus("ready");
      } catch (error) {
        if (previewRequestId.current !== requestId) return;
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        if (error instanceof PreviewTooLargeError) {
          setPreviewError("too_large");
        }
        setPreviewStatus("error");
      }
      return;
    }
    setPreviewStatus("ready");
  };

  const closeDrawer = () => {
    previewRequestId.current += 1;
    previewAbortController.current?.abort();
    previewAbortController.current = null;
    setDrawer(null);
  };

  const invokeArtifactCommand = async (
    command: "open_workspace_artifact" | "reveal_workspace_artifact",
    artifact: ArtifactEntry,
  ) => {
    if (!manifest) return;
    try {
      const resolverUrl = new URL(
        workspaceApi.getArtifactFileUriUrl(
          manifest.agent_id,
          artifact.path,
          artifact.root,
          artifact.root_ref,
        ),
        window.location.origin,
      ).toString();
      await invoke(command, {
        url: resolverUrl,
        headers: {
          ...buildAuthHeaders(),
          "X-Chat-Id": manifest.chat_id,
        },
      });
    } catch {
      message.error(
        t(
          "tool.workspaceArtifactOpenFailed",
          "Could not open workspace artifact",
        ),
      );
    }
  };

  const renderArtifact = (artifact: ArtifactEntry) => (
    <div
      className={styles.artifactRow}
      key={`${artifact.root_ref ?? artifact.root}:${artifact.path}`}
    >
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
          onClick={() => void downloadArtifact(artifact)}
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
                void invokeArtifactCommand("open_workspace_artifact", artifact)
              }
            >
              <SquareArrowOutUpRight size={15} aria-hidden="true" />
            </button>
            <button
              className={styles.iconButton}
              type="button"
              aria-label={`Reveal ${artifact.name}`}
              onClick={() =>
                void invokeArtifactCommand(
                  "reveal_workspace_artifact",
                  artifact,
                )
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
          onClose={closeDrawer}
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
                <div
                  className={styles.artifactRow}
                  key={`${change.root_ref ?? change.root}:${change.path}`}
                >
                  <ListTree size={16} aria-hidden="true" />
                  <span className={styles.fileName}>{change.path}</span>
                  <span className={styles.changeBadge}>{change.change}</span>
                </div>
              ))}
            </div>
          )}
          {drawer === "preview" && previewArtifact && (
            <div className={styles.previewBody}>
              {previewStatus === "loading" ? (
                <div className={styles.previewState}>
                  <Spin />
                </div>
              ) : previewStatus === "error" ? (
                <div className={styles.previewState} role="alert">
                  {previewError === "too_large"
                    ? t(
                        "tool.workspaceArtifactPreviewTooLarge",
                        "This file is too large to preview",
                      )
                    : t(
                        "tool.workspaceArtifactPreviewFailed",
                        "Preview failed",
                      )}
                </div>
              ) : (
                <FilePreview
                  filePath={previewArtifact.path}
                  content={previewContent}
                  chatId={manifest.chat_id}
                  root={previewArtifact.root}
                  artifactAgentId={manifest.agent_id}
                  artifactSize={previewArtifact.size}
                  previewKind={previewArtifact.preview}
                />
              )}
            </div>
          )}
        </Drawer>
      )}
    </ToolCardShell>
  );
};

export default WorkspaceArtifactsCard;
