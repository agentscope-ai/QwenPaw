import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useChatStore } from "../stores/chatStore";
import type { ChatMessage } from "../types";
import styles from "./ConversationMinimap.module.less";

const EMPTY_MESSAGES: never[] = [];

/** Extract preview text from message content */
function getMessagePreview(message: ChatMessage, maxLength = 30): string {
  if (!message.content) return "";
  for (const block of message.content) {
    if (block.type === "text" && block.text) {
      const text = block.text.trim().replace(/\n/g, " ");
      return text.length > maxLength ? text.slice(0, maxLength) + "..." : text;
    }
  }
  return "";
}

export interface ConversationMinimapProps {
  /** CSS selector to find the scroll container */
  scrollContainerSelector?: string;
  /** Whether dark mode is active */
  isDark?: boolean;
}

const ConversationMinimap: React.FC<ConversationMinimapProps> = ({
  scrollContainerSelector = "[data-minimap-scroll]",
  isDark = false,
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

  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const minimapRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLElement | null>(null);

  // Only show user messages in minimap
  const userMessages = useMemo(
    () => messages.filter((msg) => msg.role === "user"),
    [messages],
  );

  // Locate the scroll container via DOM query
  const resolveScrollContainer = useCallback(() => {
    if (scrollContainerRef.current) return scrollContainerRef.current;
    const parent = minimapRef.current?.closest("[data-minimap-root]");
    if (parent) {
      scrollContainerRef.current = parent.querySelector(
        scrollContainerSelector,
      ) as HTMLElement | null;
    }
    return scrollContainerRef.current;
  }, [scrollContainerSelector]);

  // Track which user message is currently in view
  useEffect(() => {
    const container = resolveScrollContainer();
    if (!container || userMessages.length === 0) return;

    const handleScroll = () => {
      const containerTop = container.getBoundingClientRect().top;
      const containerBottom = containerTop + container.clientHeight;
      let closestId: string | null = null;
      let closestDistance = Infinity;

      for (const msg of userMessages) {
        const element = container.querySelector(`#msg-${CSS.escape(msg.id)}`);
        if (element) {
          const rect = element.getBoundingClientRect();
          // Find the user message closest to the viewport top
          const distance = Math.abs(rect.top - containerTop);
          if (
            rect.bottom >= containerTop &&
            rect.top <= containerBottom &&
            distance < closestDistance
          ) {
            closestDistance = distance;
            closestId = msg.id;
          }
        }
      }
      setActiveMessageId(closestId);
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [userMessages, resolveScrollContainer]);

  const handleClick = useCallback(
    (messageId: string) => {
      setActiveMessageId(messageId);
      const container = resolveScrollContainer();
      if (!container) return;
      const element = container.querySelector(`#msg-${CSS.escape(messageId)}`);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    },
    [resolveScrollContainer],
  );

  if (userMessages.length <= 2) return null;

  return (
    <div
      ref={minimapRef}
      className={`${styles.minimap} ${isDark ? styles.dark : ""}`}
    >
      <div className={styles.track}>
        {userMessages.map((msg) => (
          <div
            key={msg.id}
            className={`${styles.item} ${
              msg.id === activeMessageId ? styles.itemActive : ""
            }`}
            onClick={() => handleClick(msg.id)}
          >
            <span className={styles.label}>{getMessagePreview(msg)}</span>
            <span className={styles.tick} />
          </div>
        ))}
      </div>
    </div>
  );
};

export default ConversationMinimap;
