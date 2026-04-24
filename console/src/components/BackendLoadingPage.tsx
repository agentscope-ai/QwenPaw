import { Progress } from "antd";
import { useTheme } from "../contexts/ThemeContext";
import { useTranslation } from "react-i18next";

interface BackendLoadingPageProps {
  status: "checking" | "ready" | "timeout";
  elapsed: number;
  onRetry?: () => void;
}

export default function BackendLoadingPage({
  status,
  elapsed,
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

  const statusText =
    status === "checking"
      ? elapsed === 0
        ? t("startup.starting")
        : t("startup.checking")
      : t("startup.timeout", {seconds: elapsed});

  const percent = Math.min(Math.round((elapsed / 120) * 100), 100);

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
          {/* Logo */}
          <img
            src={
              isDark
                ? "https://gw.alicdn.com/imgextra/i4/O1CN01L7e39724RlGeJYJ7l_!!6000000007388-55-tps-771-132.svg"
                : "https://gw.alicdn.com/imgextra/i1/O1CN01sens5C1TuwioeGexL_!!6000000002443-55-tps-771-132.svg"
            }
            alt="QwenPaw"
            style={{ height: 48, marginBottom: 32 }}
          />

          {/* Progress Arc */}
          <Progress
            type="dashboard"
            percent={percent}
            status={status === "timeout" ? "exception" : "active"}
            strokeColor="#ff7f16"
            trailColor={
              isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)"
            }
            gapPosition="bottom"
            format={() => <div style={{ color: textColor }}>{`${elapsed}s`}</div>}
            size={160}
            strokeWidth={8}
          />

          {/* Status text */}
          <p
            style={{
              color: status === "timeout" ? "#ff4d4f" : textColor,
              fontSize: 16,
              fontWeight: 500,
              margin: "16px 0 0",
            }}
          >
            {statusText}
          </p>

          {/* Timeout hint + retry */}
          {status === "timeout" && (
            <>
              <p
                style={{
                  color: subTextColor,
                  fontSize: 13,
                  margin: "8px 0 24px",
                }}
              >
                {t("startup.timeoutHint")}
              </p>
              <button
                onClick={onRetry}
                style={{
                  height: 40,
                  padding: "0 32px",
                  borderRadius: 8,
                  border: "none",
                  background: "#ff7f16",
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
