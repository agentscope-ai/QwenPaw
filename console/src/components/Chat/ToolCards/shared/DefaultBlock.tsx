/**
 * DefaultBlock — reusable Input/Output block with title + copy button.
 *
 * Renders declared-language content or auto-detected markdown/JSON inside a
 * bordered block with a copy button in the header.
 * - Declared language → rendered via syntax highlighting before auto-detection
 * - Markdown content → rendered via Markdown component
 * - JSON content → pretty-printed and rendered with syntax highlighting
 * - Plain text → rendered with syntax highlighting
 */

import React, { useCallback, useMemo, useRef, useState } from "react";
import { Markdown } from "@agentscope-ai/chat";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { copyText } from "@/utils/clipboard";
import { looksLikeMarkdown } from "./utils";
import styles from "./toolCards.module.less";

export interface DefaultBlockProps {
  title: string;
  content: string;
  copyTitle?: string;
  language?: string;
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

function splitStdout(content: string): { head: string; stdout: string | null } {
  const match = /^\[stdout\]\n/m.exec(content);
  if (!match || match.index === undefined)
    return { head: content, stdout: null };
  return {
    head: content.slice(0, match.index),
    stdout: content.slice(match.index + match[0].length),
  };
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
  language,
}) => {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { head, stdout } = useMemo(() => splitStdout(content), [content]);
  const declared = typeof language === "string" && language.length > 0;
  const isMarkdown = useMemo(
    () => !declared && looksLikeMarkdown(head),
    [declared, head],
  );
  const parsedJson = useMemo(
    () => (declared || isMarkdown ? null : tryParseJson(head)),
    [declared, head, isMarkdown],
  );

  const handleCopy = useCallback(() => {
    void copyText(content)
      .then(() => {
        if (timerRef.current) clearTimeout(timerRef.current);
        setCopied(true);
        timerRef.current = setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {});
  }, [content]);

  const renderContent = () => {
    if (declared) {
      return (
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          customStyle={highlighterStyle}
          wrapLongLines
        >
          {head}
        </SyntaxHighlighter>
      );
    }
    if (isMarkdown) {
      return (
        <div className={styles.defaultBlockContentMd}>
          <Markdown content={head} />
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
        {head}
      </SyntaxHighlighter>
    );
  };

  return (
    <div className={styles.defaultBlock}>
      <div className={styles.defaultBlockHeader}>
        <span className={styles.defaultBlockTitle}>{title}</span>
        <button
          type="button"
          className={styles.defaultBlockCopy}
          onClick={handleCopy}
          title={copyTitle}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
        </button>
      </div>
      {renderContent()}
      {stdout !== null && (
        <SyntaxHighlighter
          language="text"
          style={oneDark}
          customStyle={highlighterStyle}
          wrapLongLines
        >
          {stdout}
        </SyntaxHighlighter>
      )}
    </div>
  );
};

export default DefaultBlock;
