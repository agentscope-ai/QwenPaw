import { useLayoutEffect, useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatHistory, Message } from "../../api/types";
import { externalLinkMarkdownComponents } from "../../components/Markdown/externalLinkComponents";
import { groupPreviewTurns } from "./chatHistoryPreviewModel";
import { latestHistoryMarkdownChunk } from "./historyMarkdownChunks";
import styles from "./ChatHistoryPreview.module.less";

const messageType = (message: Message): string =>
  typeof message.type === "string" ? message.type : "message";
const PROCESS_PREVIEW_CHARS = 8 * 1024;

function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => {
      if (!item || typeof item !== "object") return String(item ?? "");
      const block = item as Record<string, unknown>;
      if (typeof block.text === "string") return block.text;
      if (typeof block.name === "string") return block.name;
      if (typeof block.data === "string") return block.data;
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function ProcessSummary({ messages }: { messages: Message[] }) {
  if (messages.length === 0) return null;
  return (
    <details className={styles.process}>
      <summary>{`Completed ${messages.length} steps`}</summary>
      <div className={styles.steps}>
        {messages.map((message, index) => {
          const sourceText = contentText(message.content);
          const text =
            sourceText.length > PROCESS_PREVIEW_CHARS
              ? sourceText.slice(-PROCESS_PREVIEW_CHARS)
              : sourceText;
          return (
            <div
              key={String(message.id ?? `${messageType(message)}-${index}`)}
              className={styles.step}
              data-message-type={messageType(message)}
            >
              <strong>{String(message.name ?? messageType(message))}</strong>
              {text ? <pre>{text}</pre> : null}
            </div>
          );
        })}
      </div>
    </details>
  );
}

export function ChatHistoryPreview({ history }: { history: ChatHistory }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const turns = useMemo(
    () => groupPreviewTurns(history.messages ?? []),
    [history.messages],
  );

  useLayoutEffect(() => {
    const target = scrollRef.current;
    if (target) target.scrollTop = target.scrollHeight;
  }, [turns]);

  return (
    <div className={styles.preview} data-chat-history-preview="true">
      <div ref={scrollRef} className={styles.scroll}>
        <div className={styles.history}>
          {turns.map((turn, turnIndex) => {
            const finalMessages = turn.output.filter(
              (message) =>
                message.role === "assistant" &&
                messageType(message) === "message",
            );
            const processMessages = turn.output.filter(
              (message) => !finalMessages.includes(message),
            );
            return (
              <section
                key={String(turn.user?.id ?? `turn-${turnIndex}`)}
                className={styles.turn}
                data-preview-turn={turnIndex}
              >
                {turn.user ? (
                  <div className={styles.user} data-role="user">
                    {contentText(turn.user.content)}
                  </div>
                ) : null}
                <div className={styles.assistant} data-role="assistant">
                  <ProcessSummary messages={processMessages} />
                  {finalMessages.map((message, messageIndex) => (
                    <ReactMarkdown
                      key={String(message.id ?? `answer-${messageIndex}`)}
                      remarkPlugins={[remarkGfm]}
                      components={externalLinkMarkdownComponents}
                    >
                      {latestHistoryMarkdownChunk(contentText(message.content))}
                    </ReactMarkdown>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>
      <div className={styles.composerPlaceholder} aria-hidden="true" />
    </div>
  );
}
