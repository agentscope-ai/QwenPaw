/**
 * MediaPreview — renders image / video / audio / file preview.
 *
 * Shared by all media-related tool cards (view_image, view_video,
 * desktop_screenshot, send_file_to_user, and the default fallback).
 */

import React, { useCallback, useState } from "react";
import { Attachments } from "@agentscope-ai/chat";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, ConfigProvider, Alert } from "antd";
import type { Locale } from "antd/es/locale";
import { DownloadOutlined } from "@ant-design/icons";
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
        <Alert type="warning" showIcon message={error} />
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
        <div className={styles.bubbleAudio}>
          <Audio src={media.url} onError={handleMediaError} />
        </div>
      )}
      {media.type === "file" && (
        <div className={styles.bubbleFile}>
          <Attachments.FileCard
            item={
              {
                uid: media.name,
                name: media.name,
                url: media.url,
                status: "done",
              } as any
            }
          />
          {media.url && (
            <div
              className={styles.bubbleFileDownload}
              onClick={() => openExternalLink(media.url)}
            >
              <DownloadOutlined />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default MediaPreview;
