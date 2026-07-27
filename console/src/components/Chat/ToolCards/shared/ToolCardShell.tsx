/**
 * ToolCardShell — universal wrapper for tool cards.
 *
 * Renders the compact `<details>/<summary>` layout used by ChatV2 tool
 * blocks: icon + label on a single line, expandable body underneath.
 *
 * The body is mounted lazily: `<details>` only hides content visually,
 * so without this gate every collapsed card would still parse, highlight
 * and fetch its full body on page load. Children mount on first expand
 * and stay mounted afterwards to preserve their internal state.
 */

import React, { useCallback, useState } from "react";
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
  const [hasOpened, setHasOpened] = useState(false);
  const isLoading = content.status === "calling" && isStreaming;
  const isError = content.status === "error";
  const inputProgress = content.inputProgress;
  const inputPreview = inputProgress
    ? `${inputProgress.truncated ? "…\n" : ""}${inputProgress.preview}`
    : "";

  const handleToggle = useCallback(
    (e: React.SyntheticEvent<HTMLDetailsElement>) => {
      if (e.currentTarget.open) setHasOpened(true);
    },
    [],
  );

  return (
    <details
      onToggle={handleToggle}
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
        {isLoading && inputProgress && (
          <span className={styles.toolCallInputProgress}>
            {t("tool.inputProgress", {
              count: inputProgress.characterCount,
            })}
          </span>
        )}
        {!isLoading && !isError && badges}
        {inlineResult && (
          <span className={styles.toolCallInlineResult} title={inlineResult}>
            {inlineResult}
          </span>
        )}
      </summary>
      {hasOpened &&
        (isError ? (
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
          <>
            {isLoading && inputPreview && (
              <DefaultBlock
                title={t("tool.rawInputPreview")}
                content={inputPreview}
              />
            )}
            {children}
          </>
        ))}
    </details>
  );
};

export default ToolCardShell;
