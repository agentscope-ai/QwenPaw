/**
 * DefaultBlock — reusable Input/Output block with title + copy button.
 *
 * Renders monospace text or auto-detected markdown/JSON content inside a
 * bordered block with a copy button in the header.
 * - Markdown content → rendered via Markdown component
 * - JSON content → pretty-printed and rendered as ```json code block
 * - Plain text → rendered as monospace <pre>
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

/** Render JSON with inline syntax highlighting (keys, strings, numbers, booleans, null). */
function highlightJson(obj: unknown, indent = 0): React.ReactNode[] {
  const pad = "  ".repeat(indent);
  const nodes: React.ReactNode[] = [];
  let keyCounter = 0;

  if (obj === null) {
    nodes.push(
      <span key="null" className={styles.jsonNull}>
        null
      </span>,
    );
  } else if (typeof obj === "boolean") {
    nodes.push(
      <span key="bool" className={styles.jsonNull}>
        {String(obj)}
      </span>,
    );
  } else if (typeof obj === "number") {
    nodes.push(
      <span key="num" className={styles.jsonNum}>
        {String(obj)}
      </span>,
    );
  } else if (typeof obj === "string") {
    nodes.push(<span key="str" className={styles.jsonStr}>{`"${obj}"`}</span>);
  } else if (Array.isArray(obj)) {
    if (obj.length === 0) {
      nodes.push("[]");
    } else {
      nodes.push("[\n");
      obj.forEach((item, index) => {
        nodes.push(`${pad}  `);
        nodes.push(...highlightJson(item, indent + 1));
        if (index < obj.length - 1) nodes.push(",");
        nodes.push("\n");
      });
      nodes.push(`${pad}]`);
    }
  } else if (typeof obj === "object") {
    const entries = Object.entries(obj as Record<string, unknown>);
    if (entries.length === 0) {
      nodes.push("{}");
    } else {
      nodes.push("{\n");
      entries.forEach(([key, value], index) => {
        keyCounter++;
        nodes.push(`${pad}  `);
        nodes.push(
          <span
            key={`k${keyCounter}`}
            className={styles.jsonKey}
          >{`"${key}"`}</span>,
        );
        nodes.push(": ");
        nodes.push(...highlightJson(value, indent + 1));
        if (index < entries.length - 1) nodes.push(",");
        nodes.push("\n");
      });
      nodes.push(`${pad}}`);
    }
  }
  return nodes;
}

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
        <pre className={styles.defaultBlockContent}>
          {highlightJson(parsedJson)}
        </pre>
      );
    }
    return <pre className={styles.defaultBlockContent}>{content}</pre>;
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
