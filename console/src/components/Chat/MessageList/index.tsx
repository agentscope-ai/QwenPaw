import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { DownOutlined } from "@ant-design/icons";
import { useChatStore } from "../stores/chatStore";
import MessageItem from "./MessageItem";
import styles from "./MessageList.module.less";

const EMPTY_MESSAGES: never[] = [];

export interface MessageListProps {
  /** Custom welcome screen when no messages */
  welcome?: React.ReactNode;
  /** Called when a prompt from welcome is clicked */
  onPromptClick?: (prompt: string) => void;
  /** Whether to auto-scroll on new messages */
  autoScroll?: boolean;
}

const MessageList: React.FC<MessageListProps> = ({
  welcome,
  autoScroll = true,
}) => {
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const messagesMap = useChatStore((s) => s.messages);
  const messages = useMemo(
    () =>
      activeSessionId
        ? messagesMap[activeSessionId] || EMPTY_MESSAGES
        : EMPTY_MESSAGES,
    [activeSessionId, messagesMap],
  );
  const streamingMessageId = useChatStore((s) => s.streamingMessageId);
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrollRef = useRef(false);
  const prevSessionIdRef = useRef<string | null>(null);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);

  const showWelcome = !activeSessionId || messages.length === 0;

  // Reset user-scroll flag when switching sessions
  useEffect(() => {
    if (activeSessionId !== prevSessionIdRef.current) {
      isUserScrollRef.current = false;
      prevSessionIdRef.current = activeSessionId;
    }
  }, [activeSessionId]);

  // Scroll to bottom when messages change (new messages loaded or streaming)
  useEffect(() => {
    if (showWelcome || !autoScroll || isUserScrollRef.current) return;

    const doScroll = () => {
      const container = containerRef.current;
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    };

    // Double rAF: first waits for React commit, second waits for browser layout.
    // Additional delayed scroll catches async-rendered content (images, videos).
    requestAnimationFrame(() => {
      requestAnimationFrame(doScroll);
    });
    const timer = setTimeout(doScroll, 300);
    return () => clearTimeout(timer);
  }, [messages, streamingMessageId, autoScroll, showWelcome]);

  // Detect user scroll & toggle scroll-to-bottom button
  const checkScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const { scrollTop, scrollHeight, clientHeight } = container;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    isUserScrollRef.current = !isAtBottom;
    setShowScrollToBottom(
      !isAtBottom && scrollHeight - scrollTop - clientHeight > 200,
    );
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.addEventListener("scroll", checkScrollPosition);
    return () => container.removeEventListener("scroll", checkScrollPosition);
  }, [checkScrollPosition]);

  // Re-check scroll position when content height changes (e.g. expanding
  // collapsible sections) — scrollHeight grows but no scroll event fires,
  // which could cause the scroll-to-bottom button to appear incorrectly.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const resizeObserver = new ResizeObserver(() => {
      checkScrollPosition();
    });

    // Observe the first child (the scrollable content wrapper) so we detect
    // height changes from expanded/collapsed sections, loaded images, etc.
    for (const child of Array.from(container.children)) {
      resizeObserver.observe(child);
    }

    return () => resizeObserver.disconnect();
  }, [messages, checkScrollPosition]);

  // Render welcome or messages inside the same stable container
  const renderContent = () => {
    if (showWelcome) {
      if (welcome) return welcome;
      return (
        <div className={styles.welcome}>
          <div className={styles.welcomeAvatar}>
            <img src="/qwenpaw.png" alt="QwenPaw" />
          </div>
          <div className={styles.welcomeGreeting}>Hi, how can I help you?</div>
          <div className={styles.welcomeDescription}>
            I&apos;m your AI assistant. Ask me anything.
          </div>
        </div>
      );
    }

    return messages.map((msg, idx) => (
      <div key={msg.id} id={`msg-${msg.id}`} className={styles.messageItem}>
        <MessageItem
          message={msg}
          index={idx}
          isLast={idx === messages.length - 1}
          isStreaming={msg.id === streamingMessageId}
        />
      </div>
    ));
  };

  const handleScrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      isUserScrollRef.current = false;
    }
  }, []);

  return (
    <div ref={containerRef} data-minimap-scroll className={styles.messageList}>
      {renderContent()}
      {showScrollToBottom && (
        <button
          className={styles.scrollToBottomBtn}
          onClick={handleScrollToBottom}
          aria-label="Scroll to bottom"
        >
          <DownOutlined />
        </button>
      )}
    </div>
  );
};

export default MessageList;
