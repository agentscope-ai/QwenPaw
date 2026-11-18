/**
 * MediaPreview — renders image / video / audio / file preview.
 *
 * Shared by all media-related tool cards (view_image, view_video,
 * desktop_screenshot, send_file_to_user, and the default fallback).
 */

import React, { useCallback, useEffect, useId, useState } from "react";
import { Attachments } from "@agentscope-ai/chat";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, ConfigProvider, Tooltip } from "antd";
import type { Locale } from "antd/es/locale";
import { ChevronRight, FileX2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { MediaInfo } from "./utils";
import { filePathFromPreviewUrl } from "../../../../features/files-workspace/internalFileLinks";
import { AudioDownload } from "../../MediaDownload";
import styles from "./toolCards.module.less";

export interface MediaPreviewProps {
  media: MediaInfo;
  onFileOpen?: (trigger: HTMLElement) => void;
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

const MediaPreview: React.FC<MediaPreviewProps> = ({ media, onFileOpen }) => {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [errorExpanded, setErrorExpanded] = useState(false);
  const errorDetailsId = useId();

  const resolveError = useCallback(
    ({ status, code }: { status: number; code: string }) => {
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
    },
    [t],
  );

  const handleMediaError = useCallback(() => {
    fetchPreviewError(media.url).then(resolveError);
  }, [media.url, resolveError]);

  // Reset any stale error when the media URL changes (e.g. the tool result
  // arrives with a resolved absolute path after a relative-path probe 404'd).
  useEffect(() => {
    setError(null);
    setErrorExpanded(false);
  }, [media.url]);

  // For "file" type there is no native onError — proactively HEAD-check the URL
  useEffect(() => {
    if (media.type !== "file" || !media.url) return;
    let cancelled = false;
    fetchPreviewError(media.url).then((result) => {
      if (!cancelled && result.status !== 200) {
        resolveError(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [media.type, media.url, resolveError]);

  if (error) {
    return (
      <div className={styles.toolCallMediaPreview}>
        <div className={styles.mediaErrorCard}>
          <Tooltip
            title={t(
              errorExpanded ? "preview.hideDetails" : "preview.showDetails",
            )}
          >
            <button
              type="button"
              className={styles.mediaErrorTrigger}
              aria-expanded={errorExpanded}
              aria-controls={errorDetailsId}
              onClick={(event) => {
                event.stopPropagation();
                setErrorExpanded((expanded) => !expanded);
              }}
            >
              <FileX2
                size={24}
                strokeWidth={1.5}
                className={styles.mediaErrorIcon}
                aria-hidden="true"
              />
              <span className={styles.mediaErrorLabel}>
                <span className={styles.mediaErrorName}>
                  {media.name || t("preview.unavailable")}
                </span>
                {media.name && (
                  <span className={styles.mediaErrorStatus}>
                    {t("preview.unavailable")}
                  </span>
                )}
              </span>
              <ChevronRight
                size={14}
                strokeWidth={1.5}
                className={styles.mediaErrorChevron}
                aria-hidden="true"
              />
            </button>
          </Tooltip>
          <div
            id={errorDetailsId}
            className={styles.mediaErrorDetails}
            hidden={!errorExpanded}
          >
            {media.name && (
              <div className={styles.mediaErrorFullName}>{media.name}</div>
            )}
            <div>{error}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.toolCallMediaPreview}>
      {media.type === "image" && (
        <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
          <div className={styles.toolCallImage}>
            <Image
              src={media.url}
              style={{ width: "100%", objectFit: "contain" }}
              preview={{ transitionName: "" }}
              onError={handleMediaError}
            />
          </div>
        </ConfigProvider>
      )}
      {media.type === "video" && (
        <div className={styles.bubbleVideo}>
          <Video src={media.url} controls onError={handleMediaError} />
        </div>
      )}
      {media.type === "audio" && (
        <AudioDownload url={media.url} filename={media.name}>
          <div className={styles.bubbleAudio}>
            <Audio src={media.url} onError={handleMediaError} />
          </div>
        </AudioDownload>
      )}
      {media.type === "file" && (
        <div
          className={styles.bubbleFile}
          onClickCapture={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (onFileOpen) {
              onFileOpen(event.currentTarget);
              return;
            }
            window.dispatchEvent(
              new CustomEvent("qwenpaw:open-file-preview", {
                detail: {
                  target: {
                    source: "attachment",
                    path: filePathFromPreviewUrl(media.url) || media.name,
                    artifactUrl: media.url,
                  },
                  trigger: event.currentTarget,
                },
              }),
            );
          }}
        >
          <Attachments.FileCard
            item={{
              uid: media.name,
              name: media.name,
              url: media.url,
              status: "done",
            }}
          />
        </div>
      )}
    </div>
  );
};

export default MediaPreview;
