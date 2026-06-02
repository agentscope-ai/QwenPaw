/**
 * MediaPreview — renders image / video / audio / file preview.
 *
 * Shared by all media-related tool cards (view_image, view_video,
 * desktop_screenshot, send_file_to_user, and the default fallback).
 */

import React from "react";
import { Attachments } from "@agentscope-ai/chat";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import { DownloadOutlined } from "@ant-design/icons";
import type { MediaInfo } from "./utils";
import styles from "./toolCards.module.less";

export interface MediaPreviewProps {
  media: MediaInfo;
}

const MediaPreview: React.FC<MediaPreviewProps> = ({ media }) => {
  return (
    <div className={styles.toolCallMediaPreview}>
      {media.type === "image" && (
        <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
          <div className={styles.toolCallImage}>
            <Image
              src={media.url}
              style={{ width: "100%", objectFit: "contain" }}
              preview={{ transitionName: "" }}
            />
          </div>
        </ConfigProvider>
      )}
      {media.type === "video" && (
        <div className={styles.bubbleVideo}>
          <Video src={media.url} controls />
        </div>
      )}
      {media.type === "audio" && (
        <div className={styles.bubbleAudio}>
          <Audio src={media.url} />
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
              onClick={() => window.open(media.url, "_blank")}
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
