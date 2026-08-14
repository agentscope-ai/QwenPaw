import {
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Tooltip } from "antd";
import { Download, LoaderCircle } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import Audios from "@agentscope-ai/chat/lib/DefaultCards/Audios";
import Images from "@agentscope-ai/chat/lib/DefaultCards/Images";
import Videos from "@agentscope-ai/chat/lib/DefaultCards/Videos";
import { getApiUrl } from "../../../api/config";
import { buildAuthHeaders } from "../../../api/authHeaders";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  DownloadCancelledError,
  downloadFileFromUrl,
} from "../../../utils/downloadFileFromUrl";
import styles from "./index.module.less";
import { mediaFilenameFromUrl } from "./utils";

function mediaDownloadHeaders(url: string): Record<string, string> {
  try {
    const targetOrigin = new URL(url, window.location.origin).origin;
    const pageOrigin = window.location.origin;
    const apiOrigin = new URL(getApiUrl("/"), pageOrigin).origin;
    return targetOrigin === pageOrigin || targetOrigin === apiOrigin
      ? buildAuthHeaders()
      : {};
  } catch {
    return {};
  }
}

type MediaDownloadPlacement = "audio" | "inline" | "overlay";

interface MediaDownloadProps {
  children: ReactNode;
  filename?: string;
  placement?: MediaDownloadPlacement;
  url: string;
}

interface AudioData {
  name?: string;
  src: string;
}

interface ImageData {
  name?: string;
  url: string;
}

interface VideoData {
  name?: string;
  poster?: string;
  src: string;
}

export function MediaDownload({
  children,
  filename,
  placement = "overlay",
  url,
}: MediaDownloadProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const reduceMotion = useReducedMotion();
  const [downloading, setDownloading] = useState(false);
  const mediaContentRef = useRef<HTMLDivElement>(null);
  const [audioDownloadSlot, setAudioDownloadSlot] =
    useState<HTMLSpanElement | null>(null);
  const resolvedFilename = mediaFilenameFromUrl(url, filename || "download");
  const placementClass =
    placement === "inline"
      ? styles.mediaDownloadInline
      : placement === "overlay"
      ? styles.mediaDownloadOverlay
      : "";

  useLayoutEffect(() => {
    if (placement !== "audio") {
      setAudioDownloadSlot(null);
      return;
    }

    const controller = mediaContentRef.current?.querySelector<HTMLElement>(
      '[class*="-media-player-controller"]',
    );
    const playButton = Array.from(controller?.children ?? []).find(
      (child) => child.tagName === "BUTTON",
    );
    if (!controller || !playButton) {
      setAudioDownloadSlot(null);
      return;
    }

    const slot = document.createElement("span");
    slot.className = styles.audioDownloadSlot;
    controller.insertBefore(slot, playButton.nextSibling);
    setAudioDownloadSlot(slot);

    return () => {
      slot.remove();
    };
  }, [placement]);

  const handleDownload = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDownloading(true);
    try {
      await downloadFileFromUrl(url, filename || resolvedFilename, {
        headers: mediaDownloadHeaders(url),
        errorMessage: t("files.downloadFailed"),
      });
    } catch (error) {
      if (!(error instanceof DownloadCancelledError)) {
        message.error(t("files.downloadFailed"));
      }
    } finally {
      setDownloading(false);
    }
  };

  const downloadAction = (
    <Tooltip title={t("common.download")}>
      <button
        type="button"
        className={`${styles.downloadButton} ${
          placement === "audio" ? styles.audioDownloadButton : ""
        }`}
        aria-label={t("common.download")}
        aria-busy={downloading}
        disabled={downloading}
        onClick={(event) => void handleDownload(event)}
      >
        <motion.span
          aria-hidden="true"
          animate={{ rotate: downloading && !reduceMotion ? 360 : 0 }}
          transition={
            downloading && !reduceMotion
              ? { duration: 0.8, ease: "linear", repeat: Infinity }
              : { duration: 0 }
          }
        >
          {downloading ? <LoaderCircle size={17} /> : <Download size={17} />}
        </motion.span>
      </button>
    </Tooltip>
  );

  return (
    <div className={`${styles.mediaDownload} ${placementClass}`}>
      <div ref={mediaContentRef} className={styles.mediaContent}>
        {children}
      </div>
      {placement === "audio" && audioDownloadSlot
        ? createPortal(downloadAction, audioDownloadSlot)
        : downloadAction}
    </div>
  );
}

export function DownloadableAudios({ data }: { data: AudioData[] }) {
  return (
    <div className={styles.mediaList}>
      {data.map((audio, index) => (
        <MediaDownload
          key={`${audio.src}-${index}`}
          url={audio.src}
          filename={audio.name}
          placement="audio"
        >
          <Audios data={[audio]} />
        </MediaDownload>
      ))}
    </div>
  );
}

export function DownloadableImages({ data }: { data: ImageData[] }) {
  return (
    <div className={styles.mediaList}>
      {data.map((image, index) => (
        <MediaDownload
          key={`${image.url}-${index}`}
          url={image.url}
          filename={image.name}
          placement="inline"
        >
          <Images data={[image]} />
        </MediaDownload>
      ))}
    </div>
  );
}

export function DownloadableVideos({ data }: { data: VideoData[] }) {
  return (
    <div className={styles.mediaList}>
      {data.map((video, index) => (
        <MediaDownload
          key={`${video.src}-${index}`}
          url={video.src}
          filename={video.name}
        >
          <Videos data={[video]} />
        </MediaDownload>
      ))}
    </div>
  );
}
