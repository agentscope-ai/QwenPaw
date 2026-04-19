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
  const borderColor = isDark ? "#FF7F16" : "#FF7F16";

  const statusText =
    status === "checking"
      ? elapsed === 0
        ? t("startup.starting")
        : t("startup.checking")
      : t("startup.timeout");

  return (
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

        {/* Spinner */}
        {status === "checking" && (
          <div style={{ margin: "0 auto 24px", width: 40, height: 40 }}>
            <svg
              viewBox="0 0 50 50"
              style={{ animation: "rotate 2s linear infinite", width: 40, height: 40 }}
            >
              <circle
                cx="25"
                cy="25"
                r="20"
                fill="none"
                stroke={borderColor}
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray="80, 200"
                strokeDashoffset="0"
                style={{ animation: "dash 1.5s ease-in-out infinite" }}
              />
            </svg>
            <style>{`
              @keyframes rotate {
                100% { transform: rotate(360deg); }
              }
              @keyframes dash {
                0% { stroke-dasharray: 1, 200; stroke-dashoffset: 0; }
                50% { stroke-dasharray: 90, 200; stroke-dashoffset: -35; }
                100% { stroke-dasharray: 90, 200; stroke-dashoffset: -124; }
              }
            `}</style>
          </div>
        )}

        {/* Status text */}
        <p style={{ color: textColor, fontSize: 16, fontWeight: 500, margin: "0 0 8px" }}>
          {statusText}
        </p>

        {/* Elapsed seconds */}
        {status === "checking" && elapsed > 0 && (
          <p style={{ color: subTextColor, fontSize: 13, margin: 0 }}>
            {t("startup.elapsed", { seconds: elapsed })}
          </p>
        )}

        {/* Timeout error */}
        {status === "timeout" && (
          <>
            <p style={{ color: "#ff4d4f", fontSize: 14, margin: "0 0 8px" }}>
              {t("startup.timeout", { seconds: elapsed })}
            </p>
            <p style={{ color: subTextColor, fontSize: 13, margin: "0 0 24px" }}>
              {t("startup.timeoutHint")}
            </p>
            <button
              onClick={onRetry}
              style={{
                height: 40,
                padding: "0 32px",
                borderRadius: 8,
                border: "none",
                background: borderColor,
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
  );
}
