import React, { useMemo } from "react";
import { Attachments, Markdown } from "@agentscope-ai/chat";
import { Audio, Video } from "@agentscope-ai/design";
import { Image, ConfigProvider } from "antd";
import type { Locale } from "antd/es/locale";
import { ScissorOutlined, DownloadOutlined } from "@ant-design/icons";
import { useMessageContext } from "../context/MessageContext";
import { useChatContext } from "../context/ChatContext";
import ThinkingBlock from "./ThinkingBlock";
import ToolCallBlock from "./ToolCallBlock";
import MessageActions from "./MessageActions";
import { extractText } from "../hooks/useChatMessages";
import type { MessageContent, ToolCardProps } from "../types";
import { MESSAGE_STATUS } from "../constants";
import styles from "./MessageList.module.less";

/** Format timestamp for display */
function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/** Render individual content block */
function ContentBlock({
  item,
  isStreaming,
  registry,
}: {
  item: MessageContent;
  isStreaming: boolean;
  registry: Record<string, React.FC<ToolCardProps>>;
}) {
  switch (item.type) {
    case "text": {
      // Split by \n\n into paragraphs. If 3+, show first & last, collapse middle.
      const parts = item.text.split("\n\n");
      if (parts.length >= 3) {
        const first = parts[0];
        const middle = parts.slice(1, -1).join("\n\n");
        const last = parts[parts.length - 1];
        return (
          <>
            <Markdown content={first} />
            <details className={styles.collapsibleText} open={isStreaming}>
              <summary className={styles.collapsibleSummary}>
                <span className={styles.collapsibleIcon}>
                  <ScissorOutlined />
                </span>
                <span className={styles.toolCallLabel}>折叠内容</span>
              </summary>
              <div className={styles.collapsibleBody}>
                <Markdown content={middle} />
              </div>
            </details>
            <Markdown content={last} />
          </>
        );
      }
      return <Markdown content={item.text} />;
    }
    case "thinking":
      return <ThinkingBlock content={item} isStreaming={isStreaming} />;
    case "tool_call":
      return (
        <ToolCallBlock
          content={item}
          isStreaming={isStreaming}
          registry={registry}
        />
      );
    case "image":
      return (
        <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
          <div className={styles.bubbleImage}>
            <Image
              src={item.url}
              width={56}
              height={56}
              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN88P/BfwAJhAPk4kCKsgAAAABJRU5ErkJggg=="
              preview={{ transitionName: "" }}
            />
          </div>
        </ConfigProvider>
      );
    case "video":
      return (
        <div className={styles.bubbleVideo}>
          <Video src={item.url} controls />
        </div>
      );
    case "audio":
      return (
        <div className={styles.bubbleAudio}>
          <Audio src={item.url} />
        </div>
      );
    case "file": {
      const ext = (item.name.match(/\.([^.]+)$/) || [])[1]?.toLowerCase() || "";
      const IMG_EXTS = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"];
      const VIDEO_EXTS = ["mp4", "avi", "mov", "wmv", "flv", "mkv", "webm"];
      const AUDIO_EXTS = ["mp3", "wav", "flac", "ape", "aac", "ogg", "wma"];
      if (IMG_EXTS.includes(ext)) {
        return (
          <ConfigProvider locale={{ Image: { preview: "" } } as Locale}>
            <div className={styles.bubbleImage}>
              <Image
                src={item.url}
                width={56}
                height={56}
                fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN88P/BfwAJhAPk4kCKsgAAAABJRU5ErkJggg=="
                preview={{ transitionName: "" }}
              />
            </div>
          </ConfigProvider>
        );
      }
      if (VIDEO_EXTS.includes(ext)) {
        return (
          <div className={styles.bubbleVideo}>
            <Video src={item.url} controls />
          </div>
        );
      }
      if (AUDIO_EXTS.includes(ext)) {
        return (
          <div className={styles.bubbleAudio}>
            <Audio src={item.url} />
          </div>
        );
      }
      return (
        <div className={styles.bubbleFile}>
          <Attachments.FileCard
            item={
              {
                uid: item.name,
                name: item.name,
                url: item.url,
                size: item.size,
                status: "done",
              } as any
            }
          />
          {item.url && (
            <div
              className={styles.bubbleFileDownload}
              onClick={() => window.open(item.url, "_blank")}
            >
              <DownloadOutlined />
            </div>
          )}
        </div>
      );
    }
    case "card": {
      const CardComp = registry[item.cardType];
      if (CardComp)
        return (
          <CardComp data={item.data} status="done" toolName={item.cardType} />
        );
      return null;
    }
    default:
      return null;
  }
}

const AssistantMessage: React.FC = () => {
  const { message, isStreaming } = useMessageContext();
  const { toolCardRegistry, assistantInfo } = useChatContext();
  const isError = message.status === MESSAGE_STATUS.ERROR;

  const agentName = assistantInfo?.name || "QwenPaw";
  const agentAvatar = assistantInfo?.avatar || "/qwenpaw.png";

  const copyText = useMemo(
    () => extractText(message.content),
    [message.content],
  );

  return (
    <div className={styles.assistantMessage}>
      <div className={styles.assistantAvatar}>
        <img src={agentAvatar} alt={agentName} />
      </div>
      <div className={styles.assistantContent}>
        {/* Agent info header */}
        <div className={styles.assistantHeader}>
          <span className={styles.assistantName}>{agentName}</span>
          <span className={styles.assistantTime}>
            {formatTime(message.createdAt)}
          </span>
        </div>

        {message.content.length === 0 && isStreaming && (
          <div className={styles.typingIndicator}>
            <span />
            <span />
            <span />
          </div>
        )}
        {message.content.map((item, idx) => (
          <ContentBlock
            key={idx}
            item={item}
            isStreaming={isStreaming}
            registry={toolCardRegistry}
          />
        ))}
        {isError && (
          <div className={styles.errorBadge}>Error generating response</div>
        )}
        {!isStreaming && <MessageActions textToCopy={copyText} />}
      </div>
    </div>
  );
};

export default AssistantMessage;
