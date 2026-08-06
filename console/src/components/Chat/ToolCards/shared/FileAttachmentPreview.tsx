import React from "react";
import { useTranslation } from "react-i18next";
import {
  parseInternalFileLink,
  filePathFromPreviewUrl,
} from "../../../../features/files-workspace/internalFileLinks";
import type { FileTarget } from "../../../../features/files-workspace/types";
import MediaPreview from "./MediaPreview";
import type { ToolCallContent } from "./types";
import { getFileOperationPath, getMediaInfo, shortFileName } from "./utils";
import styles from "./toolCards.module.less";

interface FileAttachmentPreviewProps {
  content: ToolCallContent;
}

function targetForPath(
  filePath: string,
  artifactUrl?: string,
): FileTarget | null {
  const workspacePath = filePath
    .trim()
    .replace(/\\/g, "/")
    .replace(/^(?:\.\/)+/, "");
  const relativeTarget = parseInternalFileLink(workspacePath);
  if (relativeTarget) {
    return { ...relativeTarget, root: "project" };
  }
  if (!filePath && !artifactUrl) return null;
  return {
    source: "attachment",
    path:
      (artifactUrl && filePathFromPreviewUrl(artifactUrl)) ||
      filePath ||
      "file",
    artifactUrl,
  };
}

function openTarget(target: FileTarget, trigger: HTMLElement) {
  window.dispatchEvent(
    new CustomEvent("qwenpaw:open-file-preview", {
      detail: { target, trigger },
    }),
  );
}

const FileAttachmentPreview: React.FC<FileAttachmentPreviewProps> = ({
  content,
}) => {
  const filePath = getFileOperationPath(content);
  const media = getMediaInfo(content);
  const target = targetForPath(filePath, media?.url);

  if (!media || media.type === "file") return null;
  return (
    <MediaPreview
      media={media}
      onFileOpen={target ? (trigger) => openTarget(target, trigger) : undefined}
    />
  );
};

export const FilePreviewLink: React.FC<FileAttachmentPreviewProps> = ({
  content,
}) => {
  const { t } = useTranslation();
  const filePath = getFileOperationPath(content);
  const media = getMediaInfo(content);
  const target = targetForPath(filePath, media?.url);
  const previewPath = filePath || media?.name || "";
  if (!previewPath || !target) return null;
  return (
    <button
      type="button"
      className={styles.filePreviewLink}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        openTarget(target, event.currentTarget);
      }}
      aria-label={`${shortFileName(previewPath)} ${t("files.preview")}`}
    >
      {t("files.preview")}
    </button>
  );
};

export default FileAttachmentPreview;
