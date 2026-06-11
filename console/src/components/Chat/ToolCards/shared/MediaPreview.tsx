/**
 * MediaPreview — renders image / video / audio / file preview.
 *
 * Shared by all media-related tool cards (view_image, view_video,
 * desktop_screenshot, send_file_to_user, and the default fallback).
 */

import React, { useCallback, useState } from "react";
import { Download, AlertTriangle, FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MediaInfo } from "./utils";
import { openExternalLink } from "../../../../utils/openExternalLink";
import styles from "./toolCards.module.less";

export interface MediaPreviewProps {
  media: MediaInfo;
}

/** Fetch the preview URL and return the HTTP status code + detail code. */
async function fetchPreviewError(
  url: string,
): Promise<{ status: number; code: string }> {
  try {
    const res = await fetch(url);
    if (res.ok) return { status: 200, code: "" };
    const body = await res.json().catch(() => null);
    return { status: res.status, code: body?.detail ?? "" };
  } catch {
    return { status: 0, code: "NETWORK_ERROR" };
  }
}

const MediaPreview: React.FC<MediaPreviewProps> = ({ media }) => {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

  const handleMediaError = useCallback(() => {
    fetchPreviewError(media.url).then(({ status, code }) => {
      const i18nKey = `preview.error.${code}`;
      const translated = t(i18nKey, { defaultValue: "" });
      if (translated) {
        setError(translated);
      } else if (status === 403) {
        setError(t("preview.error.FORBIDDEN"));
      } else if (status === 404) {
        setError(t("preview.error.NOT_FOUND"));
      } else if (code) {
        setError(t("preview.error.LOAD_FAILED_DETAIL", { detail: code }));
      } else {
        setError(t("preview.error.LOAD_FAILED"));
      }
    });
  }, [media.url, t]);

  if (error) {
    return (
      <div className={styles.toolCallMediaPreview}>
        <div className="flex items-center gap-2 rounded-md border border-yellow-200 bg-yellow-50 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 px-3 py-2 text-sm text-yellow-800 dark-mode:text-yellow-200">
          <AlertTriangle size={14} className="shrink-0" />
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.toolCallMediaPreview}>
      {media.type === "image" && (
        <div className={styles.toolCallImage}>
          <img
            src={media.url}
            alt={media.name || "image"}
            style={{ width: "100%", objectFit: "contain" }}
            onError={handleMediaError}
          />
        </div>
      )}
      {media.type === "video" && (
        <div className={styles.bubbleVideo}>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <video
            src={media.url}
            controls
            className="w-full h-full object-contain"
            onError={handleMediaError}
          />
        </div>
      )}
      {media.type === "audio" && (
        <div className={styles.bubbleAudio}>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio src={media.url} controls onError={handleMediaError} />
        </div>
      )}
      {media.type === "file" && (
        <div className={styles.bubbleFile}>
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm min-w-[160px]">
            <FileText size={16} className="shrink-0 text-muted-foreground" />
            <span className="truncate">{media.name || "file"}</span>
          </div>
          {media.url && (
            <div
              className={styles.bubbleFileDownload}
              onClick={() => openExternalLink(media.url)}
            >
              <Download size={16} />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default MediaPreview;
