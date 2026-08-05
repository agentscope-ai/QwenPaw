/**
 * ToolCardShell — universal wrapper for tool cards.
 *
 * Renders the compact `<details>/<summary>` layout used by ChatV2 tool
 * blocks: icon + label on a single line, expandable body underneath.
 *
 * When a tool is actively running (status === "calling"), a gear button
 * appears in the header. The gear button toggles an offload banner
 * below the card that lets users control background execution.
 *
 * During execution, clicking the card expands a metadata panel showing
 * tool name, call ID, and parameters.
 */

import React, { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Settings } from "lucide-react";
import type { ToolCallContent } from "./types";
import DefaultBlock from "./DefaultBlock";
import { stringifyResult } from "./utils";
import { useToolCallSessionId } from "./ToolCallSessionContext";
import { useToolCallControl } from "../../../../hooks/useToolCallControl";
import { OffloadBanner } from "./ToolCallControlPopover";
import styles from "./toolCards.module.less";
import bannerStyles from "./offloadBanner.module.less";

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

const AUTO_POPUP_TOTAL_SECS = 30;

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
  const sessionId = useToolCallSessionId();
  // Lazy-mount the expandable body: children stay unmounted until the
  // <details> is first opened, so collapsed cards never pay the render
  // cost of heavy result blocks.
  const [bodyMounted, setBodyMounted] = useState(false);
  const handleToggle = useCallback(
    (e: React.SyntheticEvent<HTMLDetailsElement>) => {
      if (e.currentTarget.open) setBodyMounted(true);
    },
    [],
  );
  const isLoading = content.status === "calling" && isStreaming;
  const isError = content.status === "error";
  const inputProgress = content.inputProgress;
  const inputPreview = inputProgress
    ? `${inputProgress.truncated ? "…\n" : ""}${inputProgress.preview}`
    : "";

  const showGear = content.status === "calling" && !!sessionId;

  const control = useToolCallControl(
    sessionId,
    content.id,
    content.status,
    content.name || title,
  );

  const gearDotClass = useMemo(() => {
    if (!control.bannerVisible) return "";
    return `${bannerStyles.show}`;
  }, [control.bannerVisible]);

  const staticMetadata = useMemo(() => {
    if (!content.params || Object.keys(content.params).length === 0)
      return null;
    const lines: string[] = [];
    if (content.id) lines.push(`tool_call_id: ${content.id}`);
    if (content.name) lines.push(`tool: ${content.name}`);
    for (const [k, v] of Object.entries(content.params)) {
      if (k === "timeout" && control.killRemaining !== null) continue;
      const val = typeof v === "string" ? v : JSON.stringify(v, null, 2);
      lines.push(`${k}: ${val}`);
    }
    return lines.join("\n");
    // control.killRemaining only gates whether to hide static "timeout" param;
    // coerce to boolean so the memo doesn't rerun every second.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    content.id,
    content.name,
    content.params,
    control.killRemaining !== null,
  ]);

  const dynamicMetadata = useMemo(() => {
    const lines: string[] = [];
    if (control.offloadRemaining !== null) {
      lines.push(`offload_remaining: ${Math.ceil(control.offloadRemaining)}s`);
    }
    if (control.killRemaining !== null) {
      lines.push(`timeout: ${Math.ceil(control.killRemaining)}s`);
    }
    return lines.length > 0 ? lines.join("\n") : null;
  }, [control.offloadRemaining, control.killRemaining]);

  return (
    <div className={styles.toolCallContainer}>
      <details
        className={`${styles.toolCallCompact} ${
          isLoading ? styles.toolCallCompactLoading : ""
        } ${isError ? styles.toolCallCompactError : ""}`}
        onToggle={handleToggle}
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

          {showGear && (
            <button
              className={`${bannerStyles.gearBtn} ${
                control.bannerVisible ? bannerStyles.active : ""
              }`}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                control.toggleBanner();
              }}
              title={t("tool.control.manage")}
            >
              <Settings size={14} aria-hidden />
              <div className={`${bannerStyles.gearDot} ${gearDotClass}`} />
            </button>
          )}
        </summary>

        {bodyMounted &&
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
              {isLoading && staticMetadata && (
                <DefaultBlock title="Parameters" content={staticMetadata} />
              )}
              {isLoading && dynamicMetadata && (
                <DefaultBlock title="Runtime" content={dynamicMetadata} />
              )}
              {children}
            </>
          ))}
      </details>

      {control.bannerVisible && showGear && (
        <OffloadBanner
          sessionId={sessionId}
          toolCallId={content.id}
          toolName={content.name || title}
          offloadRemaining={control.offloadRemaining}
          killRemaining={control.killRemaining}
          totalSeconds={AUTO_POPUP_TOTAL_SECS}
          defaultPolicy={control.defaultPolicy}
          maxInternalTimeoutSecs={control.maxInternalTimeoutSecs}
          elapsed={control.elapsed}
          onClose={control.closeBanner}
          onUpdateRemaining={control.updateRemaining}
        />
      )}
    </div>
  );
};

export default ToolCardShell;
