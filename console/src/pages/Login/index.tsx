import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Form, Input } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { authApi } from "../../api/modules/auth";
import { setApiAuthMode } from "../../api/config";
import { useAuthStore } from "../../stores/authStore";
import { useTheme } from "../../contexts/ThemeContext";
import { getPostLoginHref } from "../../utils/navigationMode";
import { PRODUCT_NAME } from "../../config/brand";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const { message } = useAppMessage();
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const rawRedirect = searchParams.get("redirect") || "/chat";
  const redirect =
    rawRedirect.startsWith("/") && !rawRedirect.startsWith("//")
      ? rawRedirect
      : "/chat";

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
    authApi
      .getStatus()
      .then((res) => {
        const mode = res.mode ?? "legacy";
        setApiAuthMode(mode);
        useAuthStore.setState({
          authEnabled: res.enabled,
          mode,
          phase: "anonymous",
        });
        if (!res.enabled) {
          finishNavigation(redirect);
          return;
        }
        setHasUsers(res.has_users);
        if (!res.has_users) {
          setIsRegister(true);
        }
      })
      .catch(() => {});
  }, [finishNavigation, redirect]);

  const onFinish = async (values: { username: string; password: string }) => {
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
      let errorMsg = t("login.failed");

      // Check if it's an Error object and use the backend message directly
      if (err instanceof Error) {
        // Use the backend message directly without complex parsing
        errorMsg = err.message;
      } else if (isRegister) {
        errorMsg = t("login.registerFailed");
      }

      message.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

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
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
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
