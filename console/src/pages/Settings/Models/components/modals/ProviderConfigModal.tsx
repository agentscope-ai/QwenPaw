import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import type { KeyboardEvent, ReactNode, UIEvent } from "react";
import {
  Form,
  Input,
  Modal,
  message,
  Button,
  Select,
  Tag,
} from "@agentscope-ai/design";
import { ApiOutlined, DownOutlined, RightOutlined } from "@ant-design/icons";
import type {
  ActiveModelsInfo,
  ProviderAuthSessionResponse,
  ProviderConfigRequest,
  ProviderInfo,
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
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
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
  const [authLoading, setAuthLoading] = useState(false);
  const [authSession, setAuthSession] =
    useState<ProviderAuthSessionResponse | null>(null);
  const [formDirty, setFormDirty] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [form] = Form.useForm<ProviderConfigFormValues>();
  const selectedChatModel = Form.useWatch("chat_model", form);
  const selectedAuthMode = Form.useWatch("auth_mode", form);
  const authPollRef = useRef<number | null>(null);
  const canEditBaseUrl = !provider.freeze_url;
  const supportsBrowserAuth =
    provider.id === "openai" && provider.auth_modes.includes("oauth_browser");
  const effectiveAuthMode =
    selectedAuthMode || provider.auth?.mode || "api_key";
  const isOauthMode =
    supportsBrowserAuth && effectiveAuthMode === "oauth_browser";

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

  const stopAuthPolling = useCallback(() => {
    if (authPollRef.current !== null) {
      window.clearInterval(authPollRef.current);
      authPollRef.current = null;
    }
  }, []);

  // Sync form when modal opens or provider data changes
  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        api_key: undefined,
        base_url: provider.base_url || undefined,
        auth_mode: provider.auth?.mode || "api_key",
        chat_model: provider.chat_model || "OpenAIChatModel",
        generate_kwargs_text:
          provider.generate_kwargs &&
          Object.keys(provider.generate_kwargs).length > 0
            ? JSON.stringify(provider.generate_kwargs, null, 2)
            : undefined,
      });
      setAdvancedOpen(false);
      setAuthSession(null);
      setFormDirty(false);
    }
    if (!open) {
      stopAuthPolling();
      setAuthSession(null);
    }
  }, [provider, form, open, stopAuthPolling]);

  useEffect(() => stopAuthPolling, [stopAuthPolling]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const generateConfig = parseGenerateConfig(values.generate_kwargs_text);
      const hasGenerateConfigInput = Boolean(
        values.generate_kwargs_text?.trim(),
      );

      if (
        values.auth_mode === "oauth_browser" &&
        currentAuthStatus !== "authorized"
      ) {
        message.warning(t("models.completeSignInBeforeSaving"));
        return;
      }

      // Validate connection before saving
      // For local providers, we might skip this or just check if models exist (which the backend does)
      if (!provider.is_custom && values.auth_mode !== "oauth_browser") {
        const result = await api.testProviderConnection(provider.id, {
          api_key: values.api_key,
          base_url: values.base_url,
          auth_mode: values.auth_mode,
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
        auth_mode: values.auth_mode,
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
        auth_mode: form.getFieldValue("auth_mode"),
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

  const currentAuthStatus = authSession?.auth?.status || provider.auth?.status;
  const currentAuthIdentity =
    authSession?.auth?.identity || provider.auth?.identity || "";
  const currentAuthError = authSession?.auth?.error || provider.auth?.error;
  const authStatusColor =
    currentAuthStatus === "authorized"
      ? "green"
      : currentAuthStatus === "authorizing"
      ? "blue"
      : currentAuthStatus === "expired" || currentAuthStatus === "error"
      ? "red"
      : "default";
  const authStatusLabel =
    currentAuthStatus === "authorized"
      ? t("models.authorized")
      : currentAuthStatus === "authorizing"
      ? t("models.authorizing")
      : currentAuthStatus === "expired"
      ? t("models.authorizationExpired")
      : currentAuthStatus === "error"
      ? t("models.authorizationError")
      : t("models.authorizationPending");

  const startAuthPolling = useCallback(
    (sessionId: string) => {
      stopAuthPolling();
      authPollRef.current = window.setInterval(async () => {
        try {
          const nextSession = await api.getProviderAuthSession(
            provider.id,
            sessionId,
          );
          setAuthSession(nextSession);
          if (nextSession.status === "authorized") {
            stopAuthPolling();
            await onSaved();
            message.success(t("models.signInSuccess", { name: provider.name }));
          } else if (nextSession.status === "error") {
            stopAuthPolling();
            message.error(nextSession.error || t("models.signInFailed"));
          }
        } catch (error) {
          stopAuthPolling();
          const errMsg =
            error instanceof Error ? error.message : t("models.signInFailed");
          message.error(errMsg);
        }
      }, 1000);
    },
    [onSaved, provider.id, provider.name, stopAuthPolling, t],
  );

  const handleStartAuth = async () => {
    setAuthLoading(true);
    try {
      const session = await api.startProviderAuth(provider.id);
      setAuthSession(session);
      if (session.auth_url) {
        window.open(session.auth_url, "_blank", "noopener,noreferrer");
      }
      startAuthPolling(session.session_id);
      message.success(t("models.signInStarted"));
    } catch (error) {
      const errMsg =
        error instanceof Error ? error.message : t("models.signInFailed");
      message.error(errMsg);
    } finally {
      setAuthLoading(false);
    }
  };

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
          stopAuthPolling();
          await api.revokeProviderAuth(provider.id);
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
            {provider.auth?.status !== "unauthorized" && (
              <Button danger size="small" onClick={handleRevoke}>
                {t("models.revokeAuthorization")}
              </Button>
            )}
            {!provider.is_custom && (
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
          auth_mode: provider.auth?.mode || "api_key",
          chat_model: provider.chat_model || "OpenAIChatModel",
          generate_kwargs_text:
            provider.generate_kwargs &&
            Object.keys(provider.generate_kwargs).length > 0
              ? JSON.stringify(provider.generate_kwargs, null, 2)
              : undefined,
        }}
        onValuesChange={() => setFormDirty(true)}
      >
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

        {supportsBrowserAuth && (
          <Form.Item
            name="auth_mode"
            label={t("models.authentication")}
            extra={t("models.authModeHint")}
          >
            <Select
              options={[
                {
                  value: "api_key",
                  label: t("models.authModeApiKey"),
                },
                {
                  value: "oauth_browser",
                  label: t("models.authModeBrowser"),
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

        {isOauthMode ? (
          <div className={styles.authPanel}>
            <div className={styles.authPanelHeader}>
              <span className={styles.authPanelTitle}>
                {t("models.currentAuthorization")}
              </span>
              <Tag color={authStatusColor}>{authStatusLabel}</Tag>
            </div>
            <div className={styles.infoRow}>
              <span className={styles.infoLabel}>
                {t("models.authorizationIdentity")}:
              </span>
              <span className={styles.authPanelValue}>
                {currentAuthIdentity || t("models.authorizationNotSignedIn")}
              </span>
            </div>
            {currentAuthError ? (
              <div className={styles.authPanelError}>
                {t("models.authorizationErrorLabel")}: {currentAuthError}
              </div>
            ) : null}
            <div className={styles.authPanelHint}>
              {t("models.codexCliRequired")}
            </div>
            {authSession?.auth_url ? (
              <div className={styles.authPanelHint}>
                {t("models.completeSignInInBrowser")}{" "}
                <a
                  href={authSession.auth_url}
                  target="_blank"
                  rel="noreferrer"
                  className={styles.authPanelLink}
                >
                  {t("models.openSignInPage")}
                </a>
              </div>
            ) : null}
            <div className={styles.authPanelActions}>
              <Button
                type="primary"
                onClick={handleStartAuth}
                loading={authLoading}
              >
                {currentAuthStatus === "authorized"
                  ? t("models.reauthorize")
                  : t("models.signInWithChatGPT")}
              </Button>
            </div>
          </div>
        ) : (
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
