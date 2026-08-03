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
import { useTranslation } from "react-i18next";
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

// Large-output guard: Prism tokenizes the whole text synchronously and emits
// one React element per token, so oversized tool results (e.g. shell stdout)
// freeze the UI thread. Above these thresholds we skip highlighting and
// render a bounded head/tail excerpt in a plain <pre>.
const LARGE_CONTENT_CHARS = 100_000;
const LARGE_CONTENT_LINES = 1_000;
const HEAD_LINES = 200;
const TAIL_LINES = 300;
const EXCERPT_MAX_CHARS = 32_000;

interface LargeExcerpt {
  head: string;
  tail: string;
  omittedLines: number;
  charTrimmed: boolean;
}

function buildLargeExcerpt(content: string): LargeExcerpt | null {
  if (content.length <= LARGE_CONTENT_CHARS) {
    let lines = 1;
    for (let i = 0; i < content.length; i += 1) {
      if (content.charCodeAt(i) === 10) {
        lines += 1;
        if (lines > LARGE_CONTENT_LINES) break;
      }
    }
    if (lines <= LARGE_CONTENT_LINES) return null;
  }

  const lines = content.split("\n");
  let head: string;
  let tail: string;
  let omittedLines = 0;
  if (lines.length > HEAD_LINES + TAIL_LINES) {
    head = lines.slice(0, HEAD_LINES).join("\n");
    tail = lines.slice(-TAIL_LINES).join("\n");
    omittedLines = lines.length - HEAD_LINES - TAIL_LINES;
  } else {
    head = content;
    tail = "";
  }
  let charTrimmed = false;
  if (head.length > EXCERPT_MAX_CHARS) {
    head = head.slice(0, EXCERPT_MAX_CHARS);
    charTrimmed = true;
  }
  if (tail.length > EXCERPT_MAX_CHARS) {
    tail = tail.slice(-EXCERPT_MAX_CHARS);
    charTrimmed = true;
  }
  return { head, tail, omittedLines, charTrimmed };
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
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { head, stdout } = useMemo(() => splitStdout(content), [content]);
  const largeContent = useMemo(
    () =>
      stdout === null
        ? content
        : [head, stdout].filter((part) => part.length > 0).join("\n"),
    [content, head, stdout],
  );
  const largeExcerpt = useMemo(
    () => buildLargeExcerpt(largeContent),
    [largeContent],
  );
  const declared = typeof language === "string" && language.length > 0;
  const isMarkdown = useMemo(
    () => !largeExcerpt && !declared && looksLikeMarkdown(head),
    [largeExcerpt, declared, head],
  );
  const parsedJson = useMemo(
    () => (largeExcerpt || declared || isMarkdown ? null : tryParseJson(head)),
    [largeExcerpt, declared, head, isMarkdown],
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
    if (largeExcerpt) {
      const {
        head: excerptHead,
        tail,
        omittedLines,
        charTrimmed,
      } = largeExcerpt;
      const notice =
        omittedLines > 0
          ? t("tool.largeOutputOmitted", { count: omittedLines })
          : charTrimmed
          ? t("tool.largeOutputTruncated")
          : null;
      return (
        <pre className={styles.defaultBlockContent}>
          {excerptHead}
          {notice && `\n\n… ${notice} …\n\n`}
          {tail}
        </pre>
      );
    }
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
      {stdout !== null && !largeExcerpt && (
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

export default React.memo(DefaultBlock);
