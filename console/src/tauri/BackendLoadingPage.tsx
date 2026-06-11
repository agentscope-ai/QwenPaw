import { type CSSProperties } from "react";
import { useTheme } from "../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import styles from "./BackendLoadingPage.module.less";
import { type BackendReadyStatus } from "./useBackendReadyPolling";

const BRAND_COLOR = "var(--primary)";
const ERROR_COLOR = "#ff4d4f";

interface BackendLoadingPageProps {
  status: BackendReadyStatus;
  elapsed: number;
  totalSec: number;
  errorMessage?: string;
  onRetry?: () => void;
}

// ── Circular progress (SVG-based, replaces antd Progress type="dashboard") ─

interface CircularProgressProps {
  percent: number;
  hasFailed: boolean;
  isDark: boolean;
}

function CircularProgress({
  percent,
  hasFailed,
  isDark,
}: CircularProgressProps) {
  const size = 160;
  const strokeWidth = 8;
  const radius = (size - strokeWidth) / 2;
  // The gauge covers 270° (bottom-gap dashboard style), starting at 135°
  const GAP_DEGREES = 90;
  const ARC_DEGREES = 360 - GAP_DEGREES;
  const circumference = 2 * Math.PI * radius;
  const arcLength = (ARC_DEGREES / 360) * circumference;
  const filledLength = (percent / 100) * arcLength;
  const trailColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)";
  const strokeColor = hasFailed ? ERROR_COLOR : BRAND_COLOR;
  // Rotate so gap is at the bottom-centre (start at 135°)
  const rotateOffset = 135;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ transform: `rotate(${rotateOffset}deg)` }}
      aria-hidden="true"
    >
      {/* Trail arc */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={trailColor}
        strokeWidth={strokeWidth}
        strokeDasharray={`${arcLength} ${circumference - arcLength}`}
        strokeLinecap="round"
      />
      {/* Filled arc */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={`${filledLength} ${circumference - filledLength}`}
        strokeLinecap="round"
        style={{ transition: "stroke-dasharray 0.4s ease" }}
      />
    </svg>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

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
        ? t("startup.starting", "Starting backend...")
        : t("startup.checking", "Connecting to backend...")
      : t("startup.timeout", {
          seconds: elapsed,
          defaultValue: "Backend failed to start within {{seconds}} seconds.",
        });

  const percent = Math.min(Math.round((elapsed / totalSec) * 100), 100);
  const style = {
    "--qwenpaw-brand-color": "var(--primary)",
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

        {/* Circular progress replacing antd Progress type="dashboard" */}
        <div className="relative inline-flex items-center justify-center">
          <CircularProgress
            percent={percent}
            hasFailed={hasFailed}
            isDark={isDark}
          />
          {/* Centre label */}
          <div
            className={styles.progressLabel}
            style={{
              position: "absolute",
              fontSize: 18,
              fontWeight: 600,
              lineHeight: 1,
            }}
          >
            {`${elapsed}s`}
          </div>
        </div>

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
                : t(
                    "startup.timeoutHint",
                    "Backend failed to start. Please retry, or check application logs for details.",
                  )}
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
              {t("startup.retry", "Retry")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
