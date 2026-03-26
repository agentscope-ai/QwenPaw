import { useState, useEffect, useMemo, useRef } from "react";
import type { KeyboardEvent, ReactNode, UIEvent } from "react";
import {
  Form,
  Input,
  Modal,
  message,
  Button,
  Select,
} from "@agentscope-ai/design";
import { ApiOutlined, DownOutlined, RightOutlined } from "@ant-design/icons";
import type {
  ProviderConfigRequest,
  DeviceAuthStartResponse,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

interface ProviderConfigFormValues
  extends Omit<ProviderConfigRequest, "generate_kwargs"> {
  generate_kwargs_text?: string;
}

interface JsonCodeEditorProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  rows?: number;
}

function highlightJson(text: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:]/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    const [token, stringToken, keySuffix] = match;

    if (match.index > lastIndex) {
      tokens.push(text.slice(lastIndex, match.index));
    }

    if (stringToken) {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={
            keySuffix ? styles.jsonEditorTokenKey : styles.jsonEditorTokenString
          }
        >
          {token}
        </span>,
      );
    } else if (token === "true" || token === "false") {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenBoolean}
        >
          {token}
        </span>,
      );
    } else if (token === "null") {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenNull}
        >
          {token}
        </span>,
      );
    } else if (/^-?\d/.test(token)) {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenNumber}
        >
          {token}
        </span>,
      );
    } else {
      tokens.push(
        <span
          key={`${match.index}-${token}`}
          className={styles.jsonEditorTokenPunctuation}
        >
          {token}
        </span>,
      );
    }

    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }

  return tokens;
}

function JsonCodeEditor({
  value = "",
  onChange,
  placeholder,
  rows = 8,
}: JsonCodeEditorProps) {
  const indentUnit = "  ";
  const highlightRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    if (!highlightRef.current) {
      return;
    }

    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab") {
      return;
    }

    event.preventDefault();

    const textarea = event.currentTarget;
    const selectionStart = textarea.selectionStart;
    const selectionEnd = textarea.selectionEnd;
    const hasSelection = selectionStart !== selectionEnd;
    const selectedText = value.slice(selectionStart, selectionEnd);

    if (!hasSelection || !selectedText.includes("\n")) {
      if (event.shiftKey) {
        const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
        const linePrefix = value.slice(lineStart, selectionStart);

        if (!linePrefix.endsWith(indentUnit)) {
          return;
        }

        const nextValue =
          value.slice(0, selectionStart - indentUnit.length) +
          value.slice(selectionStart);

        onChange?.(nextValue);

        requestAnimationFrame(() => {
          textareaRef.current?.setSelectionRange(
            selectionStart - indentUnit.length,
            selectionStart - indentUnit.length,
          );
        });
        return;
      }

      const nextValue =
        value.slice(0, selectionStart) + indentUnit + value.slice(selectionEnd);

      onChange?.(nextValue);

      requestAnimationFrame(() => {
        const nextCursor = selectionStart + indentUnit.length;
        textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
      });
      return;
    }

    const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
    const block = value.slice(lineStart, selectionEnd);
    const lines = block.split("\n");

    if (event.shiftKey) {
      const updatedLines = lines.map((line) =>
        line.startsWith(indentUnit) ? line.slice(indentUnit.length) : line,
      );
      const removedFromFirstLine = lines[0].startsWith(indentUnit)
        ? indentUnit.length
        : 0;
      const removedTotal = lines.reduce(
        (total, line) =>
          total + (line.startsWith(indentUnit) ? indentUnit.length : 0),
        0,
      );
      const nextValue =
        value.slice(0, lineStart) +
        updatedLines.join("\n") +
        value.slice(selectionEnd);

      onChange?.(nextValue);

      requestAnimationFrame(() => {
        textareaRef.current?.setSelectionRange(
          selectionStart - removedFromFirstLine,
          selectionEnd - removedTotal,
        );
      });
      return;
    }

    const updatedLines = lines.map((line) => `${indentUnit}${line}`);
    const nextValue =
      value.slice(0, lineStart) +
      updatedLines.join("\n") +
      value.slice(selectionEnd);

    onChange?.(nextValue);

    requestAnimationFrame(() => {
      textareaRef.current?.setSelectionRange(
        selectionStart + indentUnit.length,
        selectionEnd + indentUnit.length * lines.length,
      );
    });
  };

  return (
    <div className={styles.jsonEditorContainer}>
      <div
        ref={highlightRef}
        aria-hidden="true"
        className={styles.jsonEditorHighlight}
      >
        {value ? highlightJson(value) : placeholder}
        {!value && <span>{"\n"}</span>}
      </div>
      <textarea
        ref={textareaRef}
        rows={rows}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        placeholder={placeholder}
        spellCheck={false}
        className={styles.jsonEditorTextarea}
      />
    </div>
  );
}

interface ProviderConfigModalProps {
  provider: {
    id: string;
    name: string;
    api_key?: string;
    api_key_prefix?: string;
    base_url?: string;
    is_custom: boolean;
    freeze_url: boolean;
    chat_model: string;
    support_connection_check: boolean;
    generate_kwargs: Record<string, unknown>;
    supports_oauth_login: boolean;
    is_authenticated: boolean;
    auth_account_label?: string | null;
  };
  activeModels: any;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function ProviderConfigModal({
  provider,
  activeModels,
  open,
  onClose,
  onSaved,
}: ProviderConfigModalProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [formDirty, setFormDirty] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [authStarting, setAuthStarting] = useState(false);
  const [authPolling, setAuthPolling] = useState(false);
  const [authSession, setAuthSession] =
    useState<DeviceAuthStartResponse | null>(null);
  const [form] = Form.useForm<ProviderConfigFormValues>();
  const selectedChatModel = Form.useWatch("chat_model", form);
  const canEditBaseUrl = !provider.freeze_url;
  const isOauthProvider = provider.supports_oauth_login;

  const parseGenerateConfig = (value?: string) => {
    const trimmed = value?.trim();
    if (!trimmed) {
      return undefined;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      throw new Error(t("models.generateConfigInvalidJson"));
    }

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(t("models.generateConfigMustBeObject"));
    }

    return parsed as Record<string, unknown>;
  };

  const effectiveChatModel = useMemo(() => {
    if (!provider.is_custom) {
      return provider.chat_model;
    }
    return selectedChatModel || provider.chat_model || "OpenAIChatModel";
  }, [provider.chat_model, provider.is_custom, selectedChatModel]);

  const apiKeyPlaceholder = useMemo(() => {
    if (provider.api_key) {
      return t("models.leaveBlankKeep");
    }
    if (provider.api_key_prefix) {
      return t("models.enterApiKey", { prefix: provider.api_key_prefix });
    }
    return t("models.enterApiKeyOptional");
  }, [provider.api_key, provider.api_key_prefix, t]);

  const baseUrlExtra = useMemo(() => {
    if (!canEditBaseUrl) {
      return undefined;
    }
    if (provider.id === "azure-openai") {
      return t("models.azureEndpointHint");
    }
    if (provider.id === "anthropic") {
      return t("models.anthropicEndpointHint");
    }
    if (provider.id === "openai") {
      return t("models.openAIEndpoint");
    }
    if (provider.id === "github-copilot") {
      return t("models.githubCopilotEndpointHint");
    }
    if (provider.id === "ollama") {
      return t("models.ollamaEndpointHint");
    }
    if (provider.id === "lmstudio") {
      return t("models.lmstudioEndpointHint");
    }
    if (provider.is_custom) {
      return effectiveChatModel === "AnthropicChatModel"
        ? t("models.anthropicEndpointHint")
        : t("models.openAICompatibleEndpoint");
    }
    return t("models.apiEndpointHint");
  }, [canEditBaseUrl, provider.id, provider.is_custom, effectiveChatModel, t]);

  const baseUrlPlaceholder = useMemo(() => {
    if (!canEditBaseUrl) {
      return "";
    }
    if (provider.id === "azure-openai") {
      return "https://<resource>.openai.azure.com/openai/v1";
    }
    if (provider.id === "anthropic") {
      return "https://api.anthropic.com";
    }
    if (provider.id === "openai") {
      return "https://api.openai.com/v1";
    }
    if (provider.id === "github-copilot") {
      return "https://api.individual.githubcopilot.com";
    }
    if (provider.id === "ollama") {
      return "http://localhost:11434";
    }
    if (provider.id === "lmstudio") {
      return "http://localhost:1234/v1";
    }
    if (provider.is_custom && effectiveChatModel === "AnthropicChatModel") {
      return "https://api.anthropic.com";
    }
    return "https://api.example.com";
  }, [canEditBaseUrl, provider.id, provider.is_custom, effectiveChatModel]);

  // Sync form when modal opens or provider data changes
  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        api_key: undefined,
        base_url: provider.base_url || undefined,
        chat_model: provider.chat_model || "OpenAIChatModel",
        generate_kwargs_text:
          provider.generate_kwargs &&
          Object.keys(provider.generate_kwargs).length > 0
            ? JSON.stringify(provider.generate_kwargs, null, 2)
            : undefined,
      });
      setAdvancedOpen(false);
      setFormDirty(false);
      setAuthSession(null);
      setAuthPolling(false);
    }
  }, [provider, form, open]);

  useEffect(() => {
    if (!open || !authSession || !isOauthProvider) {
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setAuthPolling(true);
      try {
        const result = await api.pollDeviceAuth(provider.id, authSession.session_id);
        if (cancelled) {
          return;
        }
        if (result.status === "authorized") {
          setAuthSession(null);
          setAuthPolling(false);
          try {
            await api.discoverModels(provider.id);
          } catch {
            // Ignore model discovery failure here; auth already succeeded.
          }
          await onSaved();
          message.success(result.message || t("models.githubAuthSuccess"));
          return;
        }
        if (result.status === "pending") {
          setAuthPolling(false);
          return;
        }
        setAuthSession(null);
        setAuthPolling(false);
        message.warning(result.message || t("models.githubAuthFailed"));
      } catch (error) {
        if (!cancelled) {
          setAuthPolling(false);
          setAuthSession(null);
          message.error(
            error instanceof Error
              ? error.message
              : t("models.githubAuthFailed"),
          );
        }
      }
    }, Math.max(authSession.interval, 2) * 1000);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [authSession, isOauthProvider, onSaved, open, provider.id, t]);

  const handleStartOauthLogin = async () => {
    setAuthStarting(true);
    try {
      const session = await api.startDeviceAuth(provider.id);
      setAuthSession(session);
      window.open(session.verification_uri, "_blank", "noopener,noreferrer");
      message.info(t("models.githubAuthStarted"));
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.githubAuthFailed");
      message.error(errMsg);
    } finally {
      setAuthStarting(false);
    }
  };

  const handleCopyUserCode = async () => {
    if (!authSession?.user_code) {
      return;
    }
    try {
      await navigator.clipboard.writeText(authSession.user_code);
      message.success(t("models.githubUserCodeCopied"));
    } catch {
      message.warning(t("models.githubUserCodeCopyFailed"));
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const generateConfig = parseGenerateConfig(values.generate_kwargs_text);
      const hasGenerateConfigInput = Boolean(
        values.generate_kwargs_text?.trim(),
      );

      // Validate connection before saving
      // For local providers, we might skip this or just check if models exist (which the backend does)
      if (provider.support_connection_check) {
        const result = await api.testProviderConnection(provider.id, {
          api_key: values.api_key,
          base_url: values.base_url,
          chat_model: values.chat_model,
        });

        if (!result.success) {
          message.error(result.message || t("models.testConnectionFailed"));
          // For built-in providers, we want to enforce valid config before saving
          return;
        }
      }

      await api.configureProvider(provider.id, {
        api_key: values.api_key,
        base_url: values.base_url,
        chat_model: values.chat_model,
        generate_kwargs: hasGenerateConfigInput ? generateConfig : {},
      });

      await onSaved();
      setFormDirty(false);
      onClose();
      message.success(t("models.configurationSaved", { name: provider.name }));
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error ? error.message : t("models.failedToSaveConfig");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const values = await form.validateFields([
        "api_key",
        "base_url",
        "chat_model",
      ]);
      const result = await api.testProviderConnection(provider.id, {
        api_key: values.api_key,
        base_url: values.base_url,
        chat_model: values.chat_model,
      });
      if (result.success) {
        message.success(result.message || t("models.testConnectionSuccess"));
      } else {
        message.warning(result.message || t("models.testConnectionFailed"));
      }
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.testConnectionError");
      message.error(errMsg);
    } finally {
      setTesting(false);
    }
  };

  const isActiveLlmProvider =
    activeModels?.active_llm?.provider_id === provider.id;

  const handleRevoke = () => {
    const confirmContent = isActiveLlmProvider
      ? t("models.revokeConfirmContent", { name: provider.name })
      : t("models.revokeConfirmSimple", { name: provider.name });

    Modal.confirm({
      title: t("models.revokeAuthorization"),
      content: confirmContent,
      okText: t("models.revokeAuthorization"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          if (isOauthProvider) {
            await api.logoutProviderAuth(provider.id);
          } else {
            await api.configureProvider(provider.id, { api_key: "" });
          }
          await onSaved();
          onClose();
          if (isActiveLlmProvider) {
            message.success(
              t("models.authorizationRevoked", { name: provider.name }),
            );
          } else {
            message.success(
              t("models.authorizationRevokedSimple", { name: provider.name }),
            );
          }
        } catch (error) {
          const errMsg =
            error instanceof Error ? error.message : t("models.failedToRevoke");
          message.error(errMsg);
        }
      },
    });
  };

  return (
    <Modal
      title={t("models.configureProvider", { name: provider.name })}
      open={open}
      onCancel={onClose}
      footer={
        <div className={styles.modalFooter}>
          <div className={styles.modalFooterLeft}>
            {(isOauthProvider ? provider.is_authenticated : provider.api_key) && (
              <Button danger size="small" onClick={handleRevoke}>
                {t("models.revokeAuthorization")}
              </Button>
            )}
            {provider.support_connection_check &&
              (!isOauthProvider || provider.is_authenticated) && (
              <Button
                size="small"
                icon={<ApiOutlined />}
                onClick={handleTest}
                loading={testing}
              >
                {t("models.testConnection")}
              </Button>
            )}
          </div>
          <div className={styles.modalFooterRight}>
            <Button onClick={onClose}>{t("models.cancel")}</Button>
            <Button
              type="primary"
              loading={saving}
              disabled={!formDirty}
              onClick={handleSubmit}
            >
              {t("models.save")}
            </Button>
          </div>
        </div>
      }
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          base_url: provider.base_url || undefined,
          chat_model: provider.chat_model || "OpenAIChatModel",
          generate_kwargs_text:
            provider.generate_kwargs &&
            Object.keys(provider.generate_kwargs).length > 0
              ? JSON.stringify(provider.generate_kwargs, null, 2)
              : undefined,
        }}
        onValuesChange={() => setFormDirty(true)}
      >
        {isOauthProvider && (
          <div
            style={{
              border: "1px solid rgba(0,0,0,0.08)",
              borderRadius: 12,
              padding: 16,
              marginBottom: 16,
              background: "rgba(0,0,0,0.02)",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 8 }}>
              {t("models.githubAuthSectionTitle")}
            </div>
            <div style={{ color: "rgba(0,0,0,0.65)", marginBottom: 12 }}>
              {provider.is_authenticated
                ? t("models.githubAuthSignedInAs", {
                    account: provider.auth_account_label || provider.name,
                  })
                : t("models.githubAuthSectionDescription")}
            </div>
            {!provider.is_authenticated && (
              <Button
                type="primary"
                loading={authStarting}
                onClick={handleStartOauthLogin}
              >
                {t("models.githubLogin")}
              </Button>
            )}
            {authSession && (
              <div style={{ marginTop: 16 }}>
                <div style={{ marginBottom: 8 }}>
                  {t("models.githubAuthPendingHint")}
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    flexWrap: "wrap",
                    marginBottom: 8,
                  }}
                >
                  <Input value={authSession.user_code} readOnly style={{ width: 180 }} />
                  <Button onClick={handleCopyUserCode}>
                    {t("models.githubCopyUserCode")}
                  </Button>
                  <Button
                    onClick={() =>
                      window.open(
                        authSession.verification_uri,
                        "_blank",
                        "noopener,noreferrer",
                      )
                    }
                  >
                    {t("models.githubOpenVerificationPage")}
                  </Button>
                </div>
                <div style={{ color: "rgba(0,0,0,0.45)" }}>
                  {authPolling
                    ? t("models.githubPolling")
                    : t("models.githubWaitingForAuthorization")}
                </div>
              </div>
            )}
          </div>
        )}

        {provider.is_custom && (
          <Form.Item
            name="chat_model"
            label={t("models.protocol")}
            rules={[
              {
                required: true,
                message: t("models.selectProtocol"),
              },
            ]}
            extra={t("models.protocolHint")}
          >
            <Select
              disabled
              options={[
                {
                  value: "OpenAIChatModel",
                  label: t("models.protocolOpenAI"),
                },
                {
                  value: "AnthropicChatModel",
                  label: t("models.protocolAnthropic"),
                },
              ]}
            />
          </Form.Item>
        )}

        {/* Base URL */}
        <Form.Item
          name="base_url"
          label={t("models.baseURL")}
          rules={
            canEditBaseUrl
              ? [
                  ...(!provider.freeze_url
                    ? [
                        {
                          required: true,
                          message: t("models.pleaseEnterBaseURL"),
                        },
                      ]
                    : []),
                  {
                    validator: (_: unknown, value: string) => {
                      if (!value || !value.trim()) return Promise.resolve();
                      try {
                        const url = new URL(value.trim());
                        if (!["http:", "https:"].includes(url.protocol)) {
                          return Promise.reject(
                            new Error(t("models.pleaseEnterValidURL")),
                          );
                        }
                        return Promise.resolve();
                      } catch {
                        return Promise.reject(
                          new Error(t("models.pleaseEnterValidURL")),
                        );
                      }
                    },
                  },
                ]
              : []
          }
          extra={baseUrlExtra}
        >
          <Input placeholder={baseUrlPlaceholder} disabled={!canEditBaseUrl} />
        </Form.Item>

        {/* API Key */}
        {!isOauthProvider && (
          <Form.Item
            name="api_key"
            label={t("models.apiKey")}
            rules={[
              {
                validator: (_, value) => {
                  if (
                    value &&
                    provider.api_key_prefix &&
                    !value.startsWith(provider.api_key_prefix)
                  ) {
                    return Promise.reject(
                      new Error(
                        t("models.apiKeyShouldStart", {
                          prefix: provider.api_key_prefix,
                        }),
                      ),
                    );
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <Input.Password placeholder={apiKeyPlaceholder} />
          </Form.Item>
        )}

        <div className={styles.advancedConfigSection}>
          <button
            type="button"
            className={styles.advancedConfigToggle}
            onClick={() => setAdvancedOpen((prev) => !prev)}
          >
            <span className={styles.advancedConfigToggleLabel}>
              {advancedOpen ? <DownOutlined /> : <RightOutlined />}
              {t("models.advancedConfig")}
            </span>
          </button>

          <Form.Item
            hidden={!advancedOpen}
            name="generate_kwargs_text"
            label={t("models.generateConfig")}
            extra={t("models.generateConfigHint")}
            rules={[
              {
                validator: (_: unknown, value?: string) => {
                  try {
                    parseGenerateConfig(value);
                    return Promise.resolve();
                  } catch (error) {
                    return Promise.reject(
                      error instanceof Error
                        ? error
                        : new Error(t("models.generateConfigInvalidJson")),
                    );
                  }
                },
              },
            ]}
          >
            <JsonCodeEditor
              rows={8}
              placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
            />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
