import { useState, useEffect, useMemo } from "react";
import {
  Form,
  Input,
  Modal,
  message,
  Button,
  Select,
} from "@agentscope-ai/design";
import { ApiOutlined } from "@ant-design/icons";
import type { ProviderConfigRequest } from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

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
  const [form] = Form.useForm<ProviderConfigRequest>();
  const selectedChatModel = Form.useWatch("chat_model", form);
  const canEditBaseUrl = !provider.freeze_url;

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
      });
      setFormDirty(false);
    }
  }, [provider, form, open]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      // Validate connection before saving
      // For local providers, we might skip this or just check if models exist (which the backend does)
      const result = await api.testProviderConnection(provider.id, {
        api_key: values.api_key,
        base_url: values.base_url,
        chat_model: values.chat_model,
      });

      if (!result.success) {
        message.error(result.message || t("models.testConnectionFailed"));
        if (!provider.is_custom) {
          // For built-in providers, we want to enforce valid config before saving
          return;
        }
      }

      await api.configureProvider(provider.id, values);

      // Auto-discover models from /models endpoint so users don't need
      // to enter model IDs manually.
      // try {
      //   const discovered = await api.discoverModels(provider.id, {
      //     api_key: values.api_key,
      //     base_url: values.base_url,
      //     chat_model: values.chat_model,
      //   });
      //   if (discovered.success) {
      //     if (discovered.added_count > 0) {
      //       message.success(
      //         t("models.autoDiscoveredAndAdded", {
      //           count: discovered.models.length,
      //           added: discovered.added_count,
      //         }),
      //       );
      //     } else if (discovered.models.length > 0) {
      //       message.info(
      //         t("models.autoDiscoveredNoNew", {
      //           count: discovered.models.length,
      //         }),
      //       );
      //     }
      //   } else {
      //     message.warning(discovered.message || t("models.autoDiscoverFailed"));
      //   }
      // } catch {
      //   message.warning(t("models.autoDiscoverFailed"));
      // }

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
      const values = await form.validateFields();
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
          await api.configureProvider(provider.id, { api_key: "" });
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
            {provider.api_key && (
              <Button danger size="small" onClick={handleRevoke}>
                {t("models.revokeAuthorization")}
              </Button>
            )}
            <Button
              size="small"
              icon={<ApiOutlined />}
              onClick={handleTest}
              loading={testing}
            >
              {t("models.testConnection")}
            </Button>
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
      </Form>
    </Modal>
  );
}
