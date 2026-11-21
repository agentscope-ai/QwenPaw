import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Button, Form, Input } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import AuthBootstrapStatus from "../../components/AuthBootstrapStatus";
import { useAuthStore } from "../../stores/authStore";
import { useTheme } from "../../contexts/ThemeContext";
import { getPostLoginHref, isLoginPath } from "../../utils/navigationMode";
import { PRODUCT_NAME } from "../../config/brand";
import { AuthResponseError } from "../../api/authErrors";
import { interactionErrorText } from "../../utils/interactionText";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [feedback, setFeedback] = useState<{
    username: string;
    code: string;
    remaining?: number;
    deadline?: number;
    message: string;
  } | null>(null);
  const [now, setNow] = useState(Date.now);
  const [username, setUsername] = useState("");
  const hasUsers = useAuthStore((state) => state.hasUsers);
  const phase = useAuthStore((state) => state.phase);
  const bootstrap = useAuthStore((state) => state.bootstrap);
  const { message } = useAppMessage();
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const rawRedirect = searchParams.get("redirect") || "/chat";
  let redirect = "/chat";
  if (
    rawRedirect.startsWith("/") &&
    !rawRedirect.startsWith("//") &&
    !rawRedirect.includes("\\")
  ) {
    try {
      const target = new URL(rawRedirect, "https://app.invalid");
      const path = decodeURIComponent(target.pathname).replace(/\/+$/, "");
      if (!isLoginPath(path))
        redirect = target.pathname + target.search + target.hash;
    } catch {
      /* Malformed return paths fall back to the home chat. */
    }
  }

  const finishNavigation = useCallback(
    (target: string) => {
      const osHref = getPostLoginHref(window.location.pathname, target);
      if (osHref) {
        window.location.replace(osHref);
        return;
      }
      navigate(target, { replace: true });
    },
    [navigate],
  );

  useEffect(() => {
    if (phase === "loading") void bootstrap();
    if (phase === "authenticated" || phase === "disabled")
      finishNavigation(redirect);
  }, [phase, bootstrap, finishNavigation, redirect]);

  useEffect(() => {
    setIsRegister(!hasUsers);
  }, [hasUsers]);

  useEffect(() => {
    if (!feedback?.deadline) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [feedback?.deadline]);

  const visibleFeedback =
    feedback &&
    (feedback.username === username.trim() ||
      feedback.code === "ip_locked" ||
      feedback.code === "login_rate_limited")
      ? feedback
      : null;
  const retrySeconds = Math.max(
    0,
    Math.ceil(((visibleFeedback?.deadline ?? 0) - now) / 1000),
  );
  const countdown = `${Math.floor(retrySeconds / 60)}:${String(
    retrySeconds % 60,
  ).padStart(2, "0")}`;

  const onFinish = async (values: { username: string; password: string }) => {
    if (retrySeconds > 0) return;
    setLoading(true);
    try {
      if (isRegister) {
        await register(values.username, values.password);
        message.success(t("login.registerSuccess"));
        finishNavigation(redirect);
      } else {
        await login(values.username, values.password);
        finishNavigation(redirect);
      }
    } catch (err) {
      const detail =
        err instanceof AuthResponseError &&
        err.detail &&
        typeof err.detail === "object"
          ? (err.detail as Record<string, unknown>)
          : {};
      const errorMsg = interactionErrorText(
        err instanceof Error
          ? err.message
          : t(isRegister ? "login.registerFailed" : "login.failed"),
      );
      const seconds =
        typeof detail.retry_after_seconds === "number" &&
        Number.isFinite(detail.retry_after_seconds)
          ? Math.max(0, detail.retry_after_seconds)
          : 0;
      const remaining =
        typeof detail.remaining_attempts === "number"
          ? Math.max(0, detail.remaining_attempts)
          : undefined;
      const receivedAt = Date.now();
      setNow(receivedAt);
      setFeedback({
        username: values.username.trim(),
        code: String(detail.code ?? ""),
        remaining,
        deadline: seconds > 0 ? receivedAt + seconds * 1000 : undefined,
        message: errorMsg,
      });
      message.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  if (phase !== "anonymous") return <AuthBootstrapStatus />;

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
          padding: 32,
          borderRadius: 12,
          background: isDark ? "#1f1f1f" : "#fff",
          boxShadow: isDark
            ? "0 4px 24px rgba(0,0,0,0.4)"
            : "0 4px 24px rgba(0,0,0,0.1)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div
            aria-label={PRODUCT_NAME}
            style={{
              marginBottom: 12,
              color: isDark ? "#fff" : "#1f1f1f",
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: "0.01em",
            }}
          >
            {PRODUCT_NAME}
          </div>
          <h2 style={{ margin: 0, fontWeight: 600, fontSize: 20 }}>
            {isRegister ? t("login.registerTitle") : t("login.title")}
          </h2>
          {!hasUsers && (
            <p
              style={{
                margin: "8px 0 0",
                color: isDark ? "rgba(255,255,255,0.45)" : "#666",
                fontSize: 13,
              }}
            >
              {t("login.firstUserHint")}
            </p>
          )}
        </div>

        <Form
          layout="vertical"
          onFinish={onFinish}
          onValuesChange={(changed) => {
            if ("username" in changed)
              setUsername(String(changed.username ?? ""));
          }}
          autoComplete="off"
          size="large"
        >
          <Form.Item
            name="username"
            rules={[{ required: true, message: t("login.usernameRequired") }]}
          >
            <Input
              prefix={
                <UserOutlined
                  style={{
                    color: isDark ? "rgba(255,255,255,0.45)" : undefined,
                  }}
                />
              }
              placeholder={t("login.usernamePlaceholder")}
              autoFocus
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: t("login.passwordRequired") }]}
          >
            <Input.Password
              prefix={
                <LockOutlined
                  style={{
                    color: isDark ? "rgba(255,255,255,0.45)" : undefined,
                  }}
                />
              }
              placeholder={t("login.passwordPlaceholder")}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            {visibleFeedback && (
              <Alert
                role="alert"
                showIcon
                type={
                  retrySeconds > 0
                    ? "warning"
                    : visibleFeedback.deadline
                    ? "info"
                    : "error"
                }
                style={{ marginBottom: 16 }}
                message={
                  retrySeconds > 0
                    ? t("login.lockedCountdown", { time: countdown })
                    : visibleFeedback.deadline
                    ? t("login.lockExpired")
                    : visibleFeedback.remaining !== undefined
                    ? t("login.remainingAttempts", {
                        count: visibleFeedback.remaining,
                      })
                    : visibleFeedback.message
                }
                description={
                  retrySeconds > 0 ? (
                    <>
                      {t("login.lockedHelp")}
                      {visibleFeedback.code === "account_locked" && (
                        <Button
                          block
                          htmlType="button"
                          style={{ marginTop: 8 }}
                          onClick={() => setFeedback(null)}
                        >
                          {t(
                            "login.retryAfterUnlock",
                            "管理员已解锁，重新尝试",
                          )}
                        </Button>
                      )}
                    </>
                  ) : undefined
                }
              />
            )}
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              disabled={retrySeconds > 0}
              block
              style={{ height: 44, borderRadius: 8, fontWeight: 500 }}
            >
              {isRegister ? t("login.register") : t("login.submit")}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
}
