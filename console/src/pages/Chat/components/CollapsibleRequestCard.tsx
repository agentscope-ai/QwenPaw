/**
 * components/CollapsibleRequestCard.tsx — collapse oversized user bubbles.
 *
 * Loop modes replace the user message with a full controller prompt
 * (/mission injects ~25K characters via `_rewrite_user_msg`); the prompt is
 * persisted as a regular user message and rendered verbatim on reload,
 * drowning the original task text. This wrapper collapses such oversized
 * messages behind a short summary + expand toggle.
 *
 * The decision is purely length-based (text parts only — images/files are
 * not counted) so already-persisted histories without any metadata marker
 * are covered too, and ordinary long pastes also get a manageable bubble.
 *
 * Deliberately has ZERO dependency on @agentscope-ai/chat: the vendor card
 * arrives via `children`, which keeps this component testable without
 * mocking the SDK's deep imports.
 */
import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  COLLAPSE_THRESHOLD,
  SUMMARY_LENGTH,
  extractRequestText,
} from "./collapsibleRequest";
import styles from "./CollapsibleRequestCard.module.less";

export function CollapsibleRequestCard(props: {
  data: unknown;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const text = useMemo(() => extractRequestText(props.data), [props.data]);

  if (text.length <= COLLAPSE_THRESHOLD) {
    return <>{props.children}</>;
  }

  return (
    <div className={styles.collapsibleRequest}>
      {expanded ? (
        <>
          {props.children}
          <div className={styles.meta}>
            <span className={styles.charCount}>
              {t("chat.request.charCount", { count: text.length })}
            </span>
            <button
              type="button"
              className={styles.toggle}
              onClick={() => setExpanded(false)}
            >
              {t("chat.request.collapse")}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className={styles.summary}>
            {text.slice(0, SUMMARY_LENGTH)}
            {text.length > SUMMARY_LENGTH ? "…" : ""}
          </div>
          <div className={styles.meta}>
            <span className={styles.charCount}>
              {t("chat.request.charCount", { count: text.length })}
            </span>
            <button
              type="button"
              className={styles.toggle}
              onClick={() => setExpanded(true)}
            >
              {t("chat.request.expand")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
