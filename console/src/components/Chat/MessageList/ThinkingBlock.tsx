import React from "react";
import { useTranslation } from "react-i18next";
import { BulbOutlined } from "@ant-design/icons";
import type { ThinkingContent } from "../types";
import styles from "./MessageList.module.less";

interface ThinkingBlockProps {
  content: ThinkingContent;
  isStreaming: boolean;
}

const ThinkingBlock: React.FC<ThinkingBlockProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  // Show "thinking" spinner only when streaming AND this block is not yet collapsed
  const isThinking = isStreaming && !content.collapsed;

  // Thinking in progress: expanded; thinking done: collapsed
  return (
    <details
      className={`${styles.toolCallCompact} ${
        isThinking ? styles.toolCallCompactLoading : ""
      }`}
      open={isThinking}
    >
      <summary className={`${styles.toolCallCompactSummary} ${styles.hasIcon}`}>
        {isThinking ? (
          <span className={styles.toolCallSpinner} />
        ) : (
          <span
            className={`${styles.toolCallIcon} ${styles.toolCallIconSuccess}`}
          >
            <BulbOutlined />
          </span>
        )}
        <span className={styles.toolCallLabel}>
          {isThinking ? t("chat.thinking.thinking") : t("chat.thinking.done")}
        </span>
      </summary>
      <div className={styles.thinkingContent}>{content.text || "..."}</div>
    </details>
  );
};

export default ThinkingBlock;
