import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Checkbox, Form, Input, Modal } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  Github,
  Globe2,
  Languages,
  LockKeyhole,
  ShieldAlert,
  UserRound,
} from "lucide-react";
import { authApi } from "../../api/modules/auth";
import { setAuthToken } from "../../api/config";
import { useTheme } from "../../contexts/ThemeContext";
import { getPostLoginHref } from "../../utils/navigationMode";
import styles from "./index.module.less";

export default function LoginPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [isHub, setIsHub] = useState(false);
  const [disclaimerAccepted, setDisclaimerAccepted] = useState(false);
  const [termsOpen, setTermsOpen] = useState(false);
  const [termsRead, setTermsRead] = useState(false);
  const [pendingCredentials, setPendingCredentials] = useState<{
    username: string;
    password: string;
  } | null>(null);
  const { message } = useAppMessage();
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
        if (!res.enabled) {
          finishNavigation(redirect);
          return;
        }
        setHasUsers(res.has_users);
        setRegistrationEnabled(Boolean(res.registration_enabled));
        setIsHub(res.mode === "hub");
        if (!res.has_users) {
          setIsRegister(true);
        }
      })
      .catch(() => {});
  }, [finishNavigation, redirect]);

  const submitCredentials = async (values: {
    username: string;
    password: string;
  }) => {
    setLoading(true);
    try {
      if (isRegister) {
        const res = await authApi.register(values.username, values.password);
        if (res.token) {
          setAuthToken(res.token);
          message.success(t("login.registerSuccess"));
          finishNavigation(redirect);
        }
      } else {
        const res = await authApi.login(values.username, values.password);
        if (res.token) {
          setAuthToken(res.token);
          finishNavigation(redirect);
        } else {
          message.info(t("login.authNotEnabled"));
          finishNavigation(redirect);
        }
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

  const onFinish = async (values: { username: string; password: string }) => {
    if (isHub && !disclaimerAccepted) {
      setPendingCredentials(values);
      openTerms();
      return;
    }
    await submitCredentials(values);
  };

  const openTerms = () => {
    setTermsRead(false);
    setTermsOpen(true);
  };

  const acceptTerms = () => {
    if (!termsRead) {
      return;
    }
    setDisclaimerAccepted(true);
    setTermsOpen(false);
    if (pendingCredentials) {
      const credentials = pendingCredentials;
      setPendingCredentials(null);
      void submitCredentials(credentials);
    }
  };

  const cancelTerms = () => {
    setTermsOpen(false);
    setPendingCredentials(null);
  };

  const isChinese = (i18n.resolvedLanguage || i18n.language || "en").startsWith(
    "zh",
  );

  const switchHubLanguage = () => {
    const language = isChinese ? "en" : "zh";
    void i18n.changeLanguage(language);
    localStorage.setItem("language", language);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflowY: "auto",
        padding: "24px 16px",
        background: isDark
          ? "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)"
          : "linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)",
      }}
    >
      <div
        style={{
          width: 400,
          maxWidth: "100%",
          padding: 32,
          borderRadius: 12,
          background: isDark ? "#1f1f1f" : "#fff",
          boxShadow: isDark
            ? "0 4px 24px rgba(0,0,0,0.4)"
            : "0 4px 24px rgba(0,0,0,0.1)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <img
            src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
            alt="QwenPaw"
            style={{ height: 48, marginBottom: 12 }}
          />
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
                <UserRound
                  size={16}
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
                <LockKeyhole
                  size={16}
                  style={{
                    color: isDark ? "rgba(255,255,255,0.45)" : undefined,
                  }}
                />
              }
              placeholder={t("login.passwordPlaceholder")}
            />
          </Form.Item>

          {isHub && (
            <div className={styles.hubDisclaimer}>
              <div className={styles.disclaimerHeading}>
                <ShieldAlert size={16} aria-hidden="true" />
                <span>{t("login.hubDisclaimerTitle")}</span>
              </div>
              <ul className={styles.disclaimerPoints}>
                {[1, 2, 3].map((point) => (
                  <li key={point}>{t(`login.hubDisclaimerPoint${point}`)}</li>
                ))}
              </ul>
              <Checkbox
                checked={disclaimerAccepted}
                aria-label={t("login.hubDisclaimerAccept")}
                onChange={(event) => {
                  if (event.target.checked) {
                    openTerms();
                    return;
                  }
                  setDisclaimerAccepted(false);
                }}
              />
              <span className={styles.consentText}>
                {t("login.hubDisclaimerAcceptPrefix")}
                <button type="button" onClick={openTerms}>
                  {t("login.hubTerms")}
                </button>
              </span>
            </div>
          )}

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
        {hasUsers && registrationEnabled && (
          <Button
            type="link"
            block
            onClick={() => setIsRegister((current) => !current)}
            style={{ marginTop: 14 }}
          >
            {isRegister ? t("login.returnToSignIn") : t("login.createAccount")}
          </Button>
        )}
        {isHub && (
          <nav className={styles.hubLinks} aria-label={t("login.hubLinks")}>
            <a
              href="https://github.com/agentscope-ai/QwenPaw"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Github size={14} strokeWidth={1.8} aria-hidden="true" />
              GitHub
            </a>
            <span aria-hidden="true" />
            <a
              href="https://qwenpaw.agentscope.io/"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Globe2 size={14} strokeWidth={1.8} aria-hidden="true" />
              {t("login.officialWebsite")}
            </a>
            <span aria-hidden="true" />
            <button
              type="button"
              aria-label={t("login.switchLanguage")}
              onClick={switchHubLanguage}
            >
              <Languages size={14} strokeWidth={1.8} aria-hidden="true" />
              {isChinese ? "English" : "简体中文"}
            </button>
          </nav>
        )}
      </div>
      {isHub && (
        <Modal
          className={styles.termsModal}
          open={termsOpen}
          title={t("login.hubTermsTitle")}
          onCancel={cancelTerms}
          footer={
            <Button type="primary" disabled={!termsRead} onClick={acceptTerms}>
              {t("login.hubTermsAgree")}
            </Button>
          }
          centered
          width={620}
          destroyOnHidden
        >
          <div
            className={styles.termsScroll}
            onScroll={(event) => {
              const target = event.currentTarget;
              const remaining =
                target.scrollHeight - target.scrollTop - target.clientHeight;
              if (remaining <= 4) {
                setTermsRead(true);
              }
            }}
          >
            <p className={styles.termsLead}>{t("login.hubTermsLead")}</p>
            {[1, 2, 3, 4, 5, 6].map((section) => (
              <section key={section}>
                <h3>{t(`login.hubTermsSection${section}Title`)}</h3>
                <p>{t(`login.hubTermsSection${section}Body`)}</p>
              </section>
            ))}
            <p className={styles.termsEnd}>{t("login.hubTermsEnd")}</p>
          </div>
          {!termsRead && (
            <p className={styles.scrollHint}>{t("login.hubTermsScrollHint")}</p>
          )}
        </Modal>
      )}
    </div>
  );
}
