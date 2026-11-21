/**
 * MediaPreview — renders image / video / audio / file preview.
 *
 * Shared by all media-related tool cards (view_image, view_video,
 * desktop_screenshot, send_file_to_user, and the default fallback).
 */

import React, {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, ConfigProvider, Alert } from "antd";
import type { Locale } from "antd/es/locale";
import { useTranslation } from "react-i18next";
import type { MediaInfo } from "./utils";
import { filePathFromPreviewUrl } from "../../../../features/files-workspace/internalFileLinks";
import styles from "./toolCards.module.less";
import {
  protectedFileApiPath,
  readFileResponse,
} from "../../../../api/fileAccess";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "../../../../api/authSession";
import { useAgentStore } from "../../../../stores/agentStore";

// This vendor component imports the chat barrel internally, so keep it lazy.
const FileCard = lazy(
  () => import("@agentscope-ai/chat/lib/Attachments/FileList/FileListCard"),
);

export interface MediaPreviewProps {
  media: MediaInfo;
  onFileOpen?: (trigger: HTMLElement) => void;
}

/** Fetch the preview URL and return the HTTP status code + detail code. */
async function fetchPreviewError(
  url: string,
  agentId: string,
  signal?: AbortSignal,
): Promise<{ status: number; code: string }> {
  try {
    const path = protectedFileApiPath(url);
    const method =
      path?.startsWith("/files/preview/") ||
      /^\/console\/artifacts\/[^/]+\/download$/.test(path ?? "")
        ? "HEAD"
        : "GET";
    return await readFileResponse(
      url,
      { agentId },
      async () => ({ status: 200, code: "" }),
      { signal, method },
    );
  } catch (error) {
    const status =
      error && typeof error === "object" && "status" in error
        ? Number(error.status)
        : 0;
    return {
      status,
      code:
        status === 404
          ? "NOT_FOUND"
          : status === 401
          ? "UNAUTHORIZED"
          : status === 403
          ? "FORBIDDEN"
          : "NETWORK_ERROR",
    };
  }
}

const MediaPreview: React.FC<MediaPreviewProps> = ({ media, onFileOpen }) => {
  const generation = useSyncExternalStore(
    subscribeAccessSessionGeneration,
    getAccessSessionGeneration,
  );
  const agentId = useAgentStore((state) => state.selectedAgent);
  return (
    <ScopedMediaPreview
      key={JSON.stringify([generation, agentId, media.url])}
      media={media}
      onFileOpen={onFileOpen}
      agentId={agentId}
    />
  );
};

const ScopedMediaPreview: React.FC<MediaPreviewProps & { agentId: string }> = ({
  media,
  onFileOpen,
  agentId,
}) => {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const protectedMedia = Boolean(protectedFileApiPath(media.url));
  const displayUrl = protectedMedia ? blobUrl : media.url;

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
    fetchPreviewError(media.url, agentId).then(resolveError);
  }, [media.url, agentId, resolveError]);

  // Reset any stale error when the media URL changes (e.g. the tool result
  // arrives with a resolved absolute path after a relative-path probe 404'd).
  useEffect(() => {
    setError(null);
  }, [media.url]);

  useEffect(() => {
    if (!protectedMedia || media.type === "file") return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    void readFileResponse(
      media.url,
      { agentId },
      (response) => response.blob(),
      { signal: controller.signal },
    )
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(t("preview.error.LOAD_FAILED"));
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [media.url, media.type, protectedMedia, agentId, t]);

  // For "file" type there is no native onError — proactively HEAD-check the URL
  useEffect(() => {
    if (media.type !== "file" || !media.url) return;
    let cancelled = false;
    const controller = new AbortController();
    fetchPreviewError(media.url, agentId, controller.signal).then((result) => {
      if (!cancelled && result.status !== 200) {
        resolveError(result);
      }
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [media.type, media.url, agentId, resolveError]);

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

  if (protectedMedia && media.type !== "file" && !displayUrl)
    return (
      <div className={styles.toolCallMediaPreview}>{t("common.loading")}</div>
    );

  return (
    <div className={styles.toolCallMediaPreview}>
      {media.type === "image" && (
        <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
          <div className={styles.toolCallImage}>
            <Image
              src={displayUrl ?? undefined}
              style={{ width: "100%", objectFit: "contain" }}
              preview={{ transitionName: "" }}
              onError={handleMediaError}
            />
          </div>
        </ConfigProvider>
      )}
      {media.type === "video" && (
        <div className={styles.bubbleVideo}>
          <Video src={displayUrl ?? ""} controls onError={handleMediaError} />
        </div>
      )}
      {media.type === "audio" && (
        <div className={styles.bubbleAudio}>
          <Audio src={displayUrl ?? ""} onError={handleMediaError} />
        </div>
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
          <Suspense fallback={<span>{media.name}</span>}>
            <FileCard
              item={{
                uid: media.name,
                name: media.name,
                url: media.url,
                status: "done",
              }}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
};

export default MediaPreview;
