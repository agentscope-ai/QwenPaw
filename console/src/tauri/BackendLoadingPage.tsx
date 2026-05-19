import { Progress } from "antd";
import { useTheme } from "../contexts/ThemeContext";
import { useTranslation } from "react-i18next";

const BRAND_COLOR = "#ff7f16";
const FAILURE_COLOR = "#ff4d4f";

interface BackendLoadingPageProps {
  status: "checking" | "ready" | "timeout" | "error";
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

  const textColor = isDark ? "rgba(255,255,255,0.85)" : "#333";
  const subTextColor = isDark ? "rgba(255,255,255,0.45)" : "#888";
  const cardBg = isDark ? "#1f1f1f" : "#fff";
  const cardShadow = isDark
    ? "0 4px 24px rgba(0,0,0,0.4)"
    : "0 4px 24px rgba(0,0,0,0.1)";

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

  return (
    <>
      <style>{`
        @keyframes backend-loading-fadein {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
      <div
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: isDark
            ? "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)"
            : "linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)",
        }}
      >
        <div
          style={{
            width: 400,
            padding: 40,
            borderRadius: 12,
            background: cardBg,
            boxShadow: cardShadow,
            textAlign: "center",
            animation: "backend-loading-fadein 0.6s ease-out",
          }}
        >
          <img
            src="/qwenpaw.png"
            alt="QwenPaw"
            style={{ height: 72, marginBottom: 28 }}
          />

          {/* Progress Arc */}
          <Progress
            type="dashboard"
            percent={percent}
            status={hasFailed ? "exception" : "active"}
            strokeColor={BRAND_COLOR}
            trailColor={isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)"}
            gapPosition="bottom"
            format={() => (
              <div style={{ color: textColor }}>{`${elapsed}s`}</div>
            )}
            size={160}
            strokeWidth={8}
          />

          {/* Status text */}
          <p
            style={{
              color: hasFailed ? FAILURE_COLOR : textColor,
              fontSize: 16,
              fontWeight: 500,
              margin: "16px 0 0",
            }}
          >
            {statusText}
          </p>

          {/* Failure hint + retry */}
          {hasFailed && (
            <>
              <p
                style={{
                  color: subTextColor,
                  fontSize: 13,
                  margin: "8px 0 24px",
                }}
              >
                {status === "error"
                  ? t(
                      "startup.errorHint",
                      "The backend process could not be launched. Check application logs for details.",
                    )
                  : t("startup.timeoutHint")}
              </p>
              {errorMessage && (
                <details
                  style={{
                    margin: "0 0 24px",
                    padding: 12,
                    borderRadius: 8,
                    background: isDark
                      ? "rgba(255,255,255,0.06)"
                      : "rgba(0,0,0,0.04)",
                    textAlign: "left",
                  }}
                >
                  <summary
                    style={{
                      cursor: "pointer",
                      color: subTextColor,
                      fontSize: 12,
                      lineHeight: 1.5,
                    }}
                  >
                    {t("startup.errorDetails", "Show error details")}
                  </summary>
                  <pre
                    style={{
                      maxHeight: 96,
                      overflow: "auto",
                      margin: "8px 0 0",
                      color: subTextColor,
                      fontSize: 12,
                      lineHeight: 1.5,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {errorMessage}
                  </pre>
                </details>
              )}
              <button
                onClick={onRetry}
                style={{
                  height: 40,
                  padding: "0 32px",
                  borderRadius: 8,
                  border: "none",
                  background: BRAND_COLOR,
                  color: "#fff",
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {t("startup.retry")}
              </button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
