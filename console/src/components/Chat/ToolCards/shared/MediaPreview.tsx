/**
 * MediaPreview — renders image / video / audio / file preview.
 *
 * Shared by all media-related tool cards (view_image, view_video,
 * desktop_screenshot, send_file_to_user, and the default fallback).
 */

import React, { useCallback, useEffect, useState } from "react";
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

/** In-flight/successful HEAD probes keyed by URL, so many previews of the
 *  same file (or re-renders) trigger at most one network request. Failed
 *  probes are evicted — the file may become available later. */
const probeCache = new Map<string, Promise<{ status: number; code: string }>>();

/** Probe the preview URL with a cheap HEAD request (no body download).
 *  Servers that reject HEAD (405/501) are treated as accessible; other
 *  failures fall back to a GET to recover the error detail code. */
function probePreviewUrl(
  url: string,
): Promise<{ status: number; code: string }> {
  const cached = probeCache.get(url);
  if (cached) return cached;
  const probe = (async () => {
    try {
      const res = await fetch(url, { method: "HEAD" });
      if (res.ok || res.status === 405 || res.status === 501) {
        return { status: 200, code: "" };
      }
    } catch {
      return { status: 0, code: "NETWORK_ERROR" };
    }
    // HEAD has no body — re-fetch with GET to get the detail code.
    return fetchPreviewError(url);
  })().then((result) => {
    if (result.status !== 200) probeCache.delete(url);
    return result;
  });
  probeCache.set(url, probe);
  return probe;
}

const MediaPreview: React.FC<MediaPreviewProps> = ({ media }) => {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

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
  }, [media.url]);

  // For "file" type there is no native onError — proactively probe the URL
  useEffect(() => {
    if (media.type !== "file" || !media.url) return;
    let cancelled = false;
    probePreviewUrl(media.url).then((result) => {
      if (!cancelled && result.status !== 200) {
        resolveError(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [media.type, media.url, resolveError]);

  if (error) {
    const description = media.name ? media.name : undefined;
    return (
      <div className={styles.toolCallMediaPreview}>
        <Alert
          type="warning"
          showIcon
          message={error}
          description={description}
        />
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
              loading="lazy"
              decoding="async"
              style={{ width: "100%", objectFit: "contain" }}
              preview={{ transitionName: "" }}
              onError={handleMediaError}
            />
          </div>
        </ConfigProvider>
      )}
      {media.type === "video" && (
        <div className={styles.bubbleVideo}>
          <Video
            src={media.url}
            controls
            preload="none"
            onError={handleMediaError}
          />
        </div>
      )}
      {media.type === "audio" && (
        <div className={styles.bubbleAudio}>
          <Audio src={media.url} preload="none" onError={handleMediaError} />
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
