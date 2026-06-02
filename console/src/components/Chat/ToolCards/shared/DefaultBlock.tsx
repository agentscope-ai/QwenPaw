/**
 * DefaultBlock — reusable Input/Output block with title + copy button.
 *
 * Renders monospace text or auto-detected markdown content inside a
 * bordered block with a copy button in the header.
 */

import React, { useCallback, useMemo, useRef, useState } from "react";
import { Markdown } from "@agentscope-ai/chat";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import { looksLikeMarkdown } from "./utils";
import styles from "./toolCards.module.less";

export interface DefaultBlockProps {
  title: string;
  content: string;
  copyTitle?: string;
}

const DefaultBlock: React.FC<DefaultBlockProps> = ({
  title,
  content,
  copyTitle,
}) => {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMarkdown = useMemo(() => looksLikeMarkdown(content), [content]);

  const handleCopy = useCallback(() => {
    navigator.clipboard
      .writeText(content)
      .then(() => {
        if (timerRef.current) clearTimeout(timerRef.current);
        setCopied(true);
        timerRef.current = setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {});
  }, [content]);

  return (
    <div className={styles.defaultBlock}>
      <div className={styles.defaultBlockHeader}>
        <span className={styles.defaultBlockTitle}>{title}</span>
        <button
          className={styles.defaultBlockCopy}
          onClick={handleCopy}
          title={copyTitle}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
        </button>
      </div>
      {isMarkdown ? (
        <div className={styles.defaultBlockContentMd}>
          <Markdown content={content} />
        </div>
      ) : (
        <pre className={styles.defaultBlockContent}>{content}</pre>
      )}
    </div>
  );
};

export default DefaultBlock;
