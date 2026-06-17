/**
 * DefaultBlock — reusable Input/Output block with title + copy button.
 *
 * Renders monospace text or auto-detected markdown/JSON content inside a
 * bordered block with a copy button in the header.
 * - Markdown content → rendered via Markdown component
 * - JSON content → pretty-printed and rendered with syntax highlighting
 * - Plain text → rendered with syntax highlighting
 */

import React, { useCallback, useMemo, useRef, useState } from "react";
import { Markdown } from "@agentscope-ai/chat";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { looksLikeMarkdown } from "./utils";
import styles from "./toolCards.module.less";

export interface DefaultBlockProps {
  title: string;
  content: string;
  copyTitle?: string;
}

/** Try to parse JSON. Returns parsed object or null. */
function tryParseJson(text: string): unknown | null {
  const trimmed = text.trim();
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return null;
    }
  }
  return null;
}

const highlighterStyle = {
  margin: 0,
  borderRadius: 0,
  padding: "10px 12px",
  fontSize: "12px",
  lineHeight: "1.6",
  maxHeight: "300px",
  overflowY: "auto" as const,
};

const DefaultBlock: React.FC<DefaultBlockProps> = ({
  title,
  content,
  copyTitle,
}) => {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMarkdown = useMemo(() => looksLikeMarkdown(content), [content]);
  const parsedJson = useMemo(
    () => (isMarkdown ? null : tryParseJson(content)),
    [content, isMarkdown],
  );

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

  const renderContent = () => {
    if (isMarkdown) {
      return (
        <div className={styles.defaultBlockContentMd}>
          <Markdown content={content} />
        </div>
      );
    }
    if (parsedJson !== null) {
      return (
        <SyntaxHighlighter
          language="json"
          style={oneDark}
          customStyle={highlighterStyle}
          wrapLongLines
        >
          {JSON.stringify(parsedJson, null, 2)}
        </SyntaxHighlighter>
      );
    }
    return (
      <SyntaxHighlighter
        language="text"
        style={oneDark}
        customStyle={highlighterStyle}
        wrapLongLines
      >
        {content}
      </SyntaxHighlighter>
    );
  };

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
      {renderContent()}
    </div>
  );
};

export default DefaultBlock;
