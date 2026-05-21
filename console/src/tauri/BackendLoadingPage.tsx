import { Progress } from "antd";
import { type CSSProperties } from "react";
import { useTheme } from "../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import { QWENPAW_BRAND_COLOR, QWENPAW_ERROR_COLOR } from "../constants/colors";
import styles from "./BackendLoadingPage.module.less";
import { type BackendReadyStatus } from "./useBackendReadyPolling";

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
  const { t } = useTranslation();
  const hasFailed = status === "timeout" || status === "error";
  const statusText =
    status === "error"
      ? t("startup.error", "Backend failed to start.")
      : status === "checking"
      ? elapsed === 0
        ? t("startup.starting")
        : t("startup.checking")
      : t("startup.timeout", { seconds: elapsed });

  const percent = Math.min(Math.round((elapsed / totalSec) * 100), 100);
  const style = {
    "--qwenpaw-brand-color": QWENPAW_BRAND_COLOR,
    "--qwenpaw-error-color": QWENPAW_ERROR_COLOR,
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
          strokeColor={QWENPAW_BRAND_COLOR}
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
              {status === "error"
                ? t(
                    "startup.errorHint",
                    "The backend process could not be launched. Check application logs for details.",
                  )
                : t("startup.timeoutHint")}
            </p>
            {errorMessage && (
              <details className={styles.details}>
                <summary className={styles.summary}>
                  {t("startup.errorDetails", "Show error details")}
                </summary>
                <pre className={styles.errorDetails}>{errorMessage}</pre>
              </details>
            )}
            <button
              className={styles.retryButton}
              onClick={onRetry}
              type="button"
            >
              {t("startup.retry")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
