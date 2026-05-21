import { Progress } from "antd";
import { type CSSProperties } from "react";
import { useTheme } from "../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import styles from "./BackendLoadingPage.module.less";
import { type BackendReadyStatus } from "./useBackendReadyPolling";
import { getStartupMessages } from "./startupMessages";

const BRAND_COLOR = "#ff7f16";
const ERROR_COLOR = "#ff4d4f";

interface BackendLoadingPageProps {
  status: BackendReadyStatus;
  elapsed: number;
  totalSec: number;
  errorMessage?: string;
  onRetry?: () => void;
}

export default function BackendLoadingPage({
  status,
  elapsed,
  totalSec,
  errorMessage,
  onRetry,
}: BackendLoadingPageProps) {
  const { isDark } = useTheme();
  const { i18n } = useTranslation();
  const messages = getStartupMessages(i18n.language);
  const hasFailed = status === "timeout" || status === "error";
  const statusText =
    status === "error"
      ? messages.error
      : status === "checking"
      ? elapsed === 0
        ? messages.starting
        : messages.checking
      : messages.timeout(elapsed);

  const percent = Math.min(Math.round((elapsed / totalSec) * 100), 100);
  const style = {
    "--qwenpaw-brand-color": BRAND_COLOR,
    "--qwenpaw-error-color": ERROR_COLOR,
  } as CSSProperties;

  return (
    <div
      className={`${styles.page} ${
        isDark ? styles.pageDark : styles.pageLight
      }`}
      style={style}
    >
      <div className={styles.card}>
        <img src="/qwenpaw.png" alt="QwenPaw" className={styles.logo} />

        <Progress
          type="dashboard"
          percent={percent}
          status={hasFailed ? "exception" : "active"}
          strokeColor={BRAND_COLOR}
          trailColor={isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)"}
          gapPosition="bottom"
          format={() => (
            <div className={styles.progressLabel}>{`${elapsed}s`}</div>
          )}
          size={160}
          strokeWidth={8}
        />

        <p
          className={`${styles.statusText} ${
            hasFailed ? styles.failedText : ""
          }`}
        >
          {statusText}
        </p>

        {hasFailed && (
          <>
            <p className={styles.hint}>
              {status === "error" ? messages.errorHint : messages.timeoutHint}
            </p>
            {errorMessage && (
              <details className={styles.details}>
                <summary className={styles.summary}>
                  {messages.errorDetails}
                </summary>
                <pre className={styles.errorDetails}>{errorMessage}</pre>
              </details>
            )}
            <button
              className={styles.retryButton}
              onClick={onRetry}
              type="button"
            >
              {messages.retry}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
