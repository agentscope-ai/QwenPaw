import React, { useMemo } from "react";
import { Attachments, Markdown } from "@agentscope-ai/chat";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, Space, ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import { DownloadOutlined } from "@ant-design/icons";
import { useMessageContext } from "../context/MessageContext";

// File type detection
const IMG_EXTS = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"];
const VIDEO_EXTS = ["mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"];
const AUDIO_EXTS = ["mp3", "wav", "flac", "ape", "aac", "ogg", "wma"];

function getFileExt(name: string): string {
  const match = name.match(/\.([^.]+)$/);
  return match ? match[1].toLowerCase() : "";
}
import MessageActions from "./MessageActions";
import { extractText } from "../hooks/useChatMessages";
import type { MessageContent } from "../types";
import styles from "./MessageList.module.less";

// ---------------------------------------------------------------------------
// Sub-components (matching WebUI DefaultCards pattern)
// ---------------------------------------------------------------------------

/** Image with click-to-preview (same as WebUI Images card) */
function ImagePreview({ url }: { url: string }) {
  return (
    <div className={styles.bubbleImage}>
      <Image
        src={url}
        width={56}
        height={56}
        fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN88P/BfwAJhAPk4kCKsgAAAABJRU5ErkJggg=="
        preview={{ transitionName: "" }}
      />
    </div>
  );
}

/** File card with hover download overlay (same as WebUI Files card) */
function FileCard({
  name,
  url,
  size,
}: {
  name: string;
  url: string;
  size?: number;
}) {
  return (
    <div className={styles.bubbleFile}>
      <Attachments.FileCard
        item={{ uid: name, name, url, size, status: "done" } as any}
      />
      {url && (
        <div
          className={styles.bubbleFileDownload}
          onClick={() => window.open(url, "_blank")}
        >
          <DownloadOutlined />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content rendering
// ---------------------------------------------------------------------------

function renderContent(content: MessageContent[]) {
  const textItems: React.ReactNode[] = [];
  const attachmentItems: React.ReactNode[] = [];

  content.forEach((item, idx) => {
    switch (item.type) {
      case "text": {
        const t = item.text;
        if (
          t.startsWith("用户上传文件，已经下载到") ||
          t.startsWith("User uploaded a file, downloaded to")
        ) {
          break;
        }
        textItems.push(
          <div key={`t${idx}`} className={styles.userText}>
            <Markdown content={t} />
          </div>,
        );
        break;
      }
      case "image":
        attachmentItems.push(<ImagePreview key={`i${idx}`} url={item.url} />);
        break;
      case "video":
        attachmentItems.push(
          <div key={`v${idx}`} className={styles.bubbleVideo}>
            <Video src={item.url} controls />
          </div>,
        );
        break;
      case "audio":
        attachmentItems.push(
          <div key={`a${idx}`} className={styles.bubbleAudio}>
            <Audio src={item.url} />
          </div>,
        );
        break;
      case "file": {
        const ext = getFileExt(item.name);
        if (IMG_EXTS.includes(ext)) {
          attachmentItems.push(<ImagePreview key={`f${idx}`} url={item.url} />);
        } else if (VIDEO_EXTS.includes(ext)) {
          attachmentItems.push(
            <div key={`f${idx}`} className={styles.bubbleVideo}>
              <Video src={item.url} controls />
            </div>,
          );
        } else if (AUDIO_EXTS.includes(ext)) {
          attachmentItems.push(
            <div key={`f${idx}`} className={styles.bubbleAudio}>
              <Audio src={item.url} />
            </div>,
          );
        } else {
          attachmentItems.push(
            <FileCard
              key={`f${idx}`}
              name={item.name}
              url={item.url}
              size={item.size}
            />,
          );
        }
        break;
      }
      default:
        break;
    }
  });

  return (
    <>
      {textItems}
      {attachmentItems.length > 0 && (
        <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
          <Space className={styles.userAttachments} wrap>
            {attachmentItems}
          </Space>
        </ConfigProvider>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const UserMessage: React.FC = () => {
  const { message } = useMessageContext();

  const copyText = useMemo(
    () => extractText(message.content),
    [message.content],
  );

  return (
    <div className={styles.userMessage}>
      <div className={styles.userBubbleWrapper}>
        <div className={styles.userBubble}>
          <div className={styles.userContent}>
            {renderContent(message.content)}
          </div>
        </div>
        <MessageActions textToCopy={copyText} />
      </div>
    </div>
  );
};

export default UserMessage;
