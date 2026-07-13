/**
 * ToolCardShell — universal wrapper for tool cards.
 *
 * Renders the compact `<details>/<summary>` layout used by ChatV2 tool
 * blocks: icon + label on a single line, expandable body underneath.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import type { ToolCallContent } from "./types";
import DefaultBlock from "./DefaultBlock";
import { stringifyResult } from "./utils";
import styles from "./toolCards.module.less";

export interface ToolCardShellProps {
  /** Full ToolCallContent (name, params, result, status). */
  content: ToolCallContent;
  /** Whether the parent message is still streaming. */
  isStreaming?: boolean;
  /** Icon element (antd icon). */
  icon: React.ReactNode;
  /** Human-readable title to show in the summary line. */
  title: string;
  /** Optional inline result shown after the title when status === done. */
  inlineResult?: string | null;
  /** Optional badge elements (line counts, diff counts). */
  badges?: React.ReactNode;
  /** Expandable body content. */
  children?: React.ReactNode;
}

const ToolCardShell: React.FC<ToolCardShellProps> = ({
  content,
  isStreaming = false,
  icon,
  title,
  inlineResult,
  badges,
  children,
}) => {
  const { t } = useTranslation();
  const isLoading = content.status === "calling" && isStreaming;
  const isError = content.status === "error";

  return (
    <details
      className={`${styles.toolCallCompact} ${
        isLoading ? styles.toolCallCompactLoading : ""
      } ${isError ? styles.toolCallCompactError : ""}`}
    >
      <summary className={styles.toolCallCompactSummary}>
        {isLoading ? (
          <span className={styles.toolCallSpinner} />
        ) : (
          <span
            className={`${styles.toolCallIcon} ${
              isError ? styles.toolCallIconError : styles.toolCallIconSuccess
            }`}
          >
            {icon}
          </span>
        )}
        <span className={styles.toolCallLabel} title={title}>
          {title}
          {isLoading && ` ${t("tool.loading")}`}
        </span>
        {!isLoading && !isError && badges}
        {inlineResult && (
          <span className={styles.toolCallInlineResult} title={inlineResult}>
            {inlineResult}
          </span>
        )}
      </summary>
      {isError ? (
        <>
          <DefaultBlock
            title="Input"
            content={JSON.stringify(content.params, null, 2)}
          />
          <DefaultBlock
            title="Error"
            content={stringifyResult(content.result)}
          />
        </>
      ) : (
        children
      )}
    </details>
  );
};

export default ToolCardShell;
