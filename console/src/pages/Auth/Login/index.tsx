import {
  MessageOutlined,
  MobileOutlined,
} from "@ant-design/icons";
import { Alert, Card, Form, Input, Select, Typography, message } from "antd";
import { Button } from "@agentscope-ai/design";
import { useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  FALLBACK_AUTH_META,
} from "../../../auth/proboost/config";
import { fetchAuthMeta } from "../../../auth/proboost/client";
import type { ProBoostAuthMeta } from "../../../auth/proboost/types";
import { useAuth } from "../../../auth/useAuth";

interface AuthFormValues {
  countryCode: string;
  phone: string;
  smsCode: string;
}

export default function LoginPage() {
  const { t } = useTranslation();
  const { register, sendSmsCode, isAuthenticated } = useAuth();
  const location = useLocation();
  const [form] = Form.useForm<AuthFormValues>();
  const [messageApi, messageContextHolder] = message.useMessage();
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [authMeta, setAuthMeta] = useState<ProBoostAuthMeta>(FALLBACK_AUTH_META);

  const redirectPath = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const redirect = params.get("redirect");
    return redirect?.startsWith("/") ? redirect : "/chat";
  }, [location.search]);

  const countryCodeOptions = useMemo(
    () =>
      authMeta.countryCodeOptions.map((option) => ({
        label: option.labelKey ? t(option.labelKey, { code: option.value }) : option.value,
        value: option.value,
      })),
    [authMeta.countryCodeOptions, t],
  );

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = window.setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [secondsLeft]);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthMeta()
      .then((meta) => {
        if (cancelled) return;
        setAuthMeta(meta);
        const current = form.getFieldValue("countryCode") as string | undefined;
        if (
          !current ||
          current === FALLBACK_AUTH_META.defaultCountryCode ||
          !meta.supportedCountryCodes.includes(current)
        ) {
          form.setFieldsValue({ countryCode: meta.defaultCountryCode });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [form]);

  if (isAuthenticated) {
    return <Navigate to={redirectPath} replace />;
  }

  const onFinish = async (values: AuthFormValues) => {
    setLoading(true);
    setErrorText("");
    try {
      await register(values.phone.trim(), values.smsCode.trim(), values.countryCode);
    } catch (error) {
      const fallback = t("auth.loginFailed");
      setErrorText(error instanceof Error ? error.message || fallback : fallback);
      setLoading(false);
    }
  };

  const handleSendCode = async () => {
    setErrorText("");
    try {
      const { phone, countryCode } = await form
        .validateFields(["countryCode", "phone"])
        .then((v) => ({ phone: v.phone, countryCode: v.countryCode }));
      setSendingCode(true);
      await sendSmsCode(phone.trim(), countryCode);
      setSecondsLeft(60);
      messageApi.success(t("auth.sendCodeSuccess"));
    } catch (error) {
      if (error instanceof Error) {
        setErrorText(error.message || t("auth.sendCodeFailed"));
      } else if (!(error as { errorFields?: unknown }).errorFields) {
        setErrorText(t("auth.sendCodeFailed"));
      }
    } finally {
      setSendingCode(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#f7f8fa",
        padding: 24,
      }}
    >
      {messageContextHolder}
      <Card style={{ width: "100%", maxWidth: 420 }}>
        <Typography.Title level={3} style={{ marginBottom: 8 }}>
          {t("auth.title")}
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
          {t("auth.subtitle")}
        </Typography.Paragraph>

        {errorText && (
          <Alert type="error" showIcon message={errorText} style={{ marginBottom: 16 }} />
        )}

        <Form<AuthFormValues>
          form={form}
          layout="vertical"
          onFinish={onFinish}
          autoComplete="off"
          initialValues={{ countryCode: FALLBACK_AUTH_META.defaultCountryCode }}
        >
          <div style={{ display: "flex", gap: 12 }}>
            <Form.Item
              name="countryCode"
              label={t("auth.countryCode")}
              rules={[{ required: true, message: t("auth.countryCodeRequired") }]}
              style={{ width: 160, marginBottom: 24 }}
            >
              <Select options={countryCodeOptions} />
            </Form.Item>

            <Form.Item
              name="phone"
              label={t("auth.phone")}
              rules={[{ required: true, message: t("auth.phoneRequired") }]}
              style={{ flex: 1, marginBottom: 24 }}
            >
              <Input prefix={<MobileOutlined />} placeholder={t("auth.phonePlaceholder")} />
            </Form.Item>
          </div>

          <Form.Item
            name="smsCode"
            label={t("auth.smsCode")}
            rules={[{ required: true, message: t("auth.smsCodeRequired") }]}
          >
            <Input
              prefix={<MessageOutlined />}
              placeholder={t("auth.smsCodePlaceholder")}
            />
          </Form.Item>

          <Form.Item style={{ marginTop: -8 }}>
            <Button
              type="default"
              onClick={handleSendCode}
              loading={sendingCode}
              disabled={secondsLeft > 0}
              block
            >
              {secondsLeft > 0
                ? t("auth.resendCodeIn", { seconds: secondsLeft })
                : t("auth.sendCode")}
            </Button>
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button htmlType="submit" type="primary" loading={loading} block>
              {t("auth.signIn")}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
