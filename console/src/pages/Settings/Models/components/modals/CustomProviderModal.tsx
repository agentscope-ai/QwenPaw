import { useEffect, useState } from "react";
import { Button, Form, Input, Modal, Select } from "@agentscope-ai/design";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import styles from "../../index.module.less";

interface CustomProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

export function CustomProviderModal({
  open,
  onClose,
  onSaved,
}: CustomProviderModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const [createdProviderId, setCreatedProviderId] = useState<string | null>(
    null,
  );
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open) return;
    setSaving(false);
    setCreatedProviderId(null);
    form.resetFields();
  }, [form, open]);

  const createOrUpdateProvider = async () => {
    const values = await form.validateFields();
    let providerId = createdProviderId;

    if (!providerId) {
      const created = await api.createCustomProvider({
        id: values.id.trim(),
        name: values.name.trim(),
        default_base_url: values.default_base_url.trim(),
        chat_model: values.chat_model || "OpenAIChatModel",
      });
      providerId = created.id;
      setCreatedProviderId(providerId);
    }

    await api.configureProvider(providerId, {
      api_key: values.api_key?.trim() || "",
      name: values.name.trim(),
      base_url: values.default_base_url.trim(),
      chat_model: values.chat_model || "OpenAIChatModel",
      auto_discover: false,
    });

    return values.name.trim();
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      const providerName = await createOrUpdateProvider();
      await onSaved();
      message.success(t("models.configurationSaved", { name: providerName }));
      onClose();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) {
        return;
      }
      const errorMessage =
        error instanceof Error
          ? error.message
          : t("models.providerCreateFailed");
      message.error(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("models.addProviderTitle")}
      open={open}
      onCancel={onClose}
      width={720}
      className={styles.modelManageModal}
      footer={
        <div className={styles.modalActionRow}>
          <Button disabled={saving} onClick={onClose}>
            {t("models.cancel")}
          </Button>
          <Button type="primary" loading={saving} onClick={handleSave}>
            {t("models.save")}
          </Button>
        </div>
      }
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 16 }}
        initialValues={{ chat_model: "OpenAIChatModel" }}
      >
        <Form.Item
          name="id"
          label={t("models.providerIdLabel")}
          extra={t("models.providerIdHint")}
          rules={[
            { required: true, message: t("models.providerIdLabel") },
            {
              pattern: /^[a-z][a-z0-9_-]{0,63}$/,
              message: t("models.providerIdHint"),
            },
          ]}
        >
          <Input
            disabled={Boolean(createdProviderId)}
            placeholder={t("models.providerIdPlaceholder")}
          />
        </Form.Item>

        <Form.Item
          name="name"
          label={t("models.providerNameLabel")}
          rules={[{ required: true, message: t("models.providerNameLabel") }]}
        >
          <Input placeholder={t("models.providerNamePlaceholder")} />
        </Form.Item>

        <Form.Item
          name="default_base_url"
          label={t("models.defaultBaseUrlLabel")}
          rules={[
            {
              required: true,
              message: t("models.pleaseEnterBaseURL"),
            },
            {
              validator: (_: unknown, value?: string) => {
                if (!value?.trim()) return Promise.resolve();
                try {
                  const url = new URL(value.trim());
                  if (!["http:", "https:"].includes(url.protocol)) {
                    throw new Error();
                  }
                  return Promise.resolve();
                } catch {
                  return Promise.reject(
                    new Error(t("models.pleaseEnterValidURL")),
                  );
                }
              },
            },
          ]}
        >
          <Input placeholder={t("models.defaultBaseUrlPlaceholder")} />
        </Form.Item>

        <Form.Item name="api_key" label={t("models.apiKey")}>
          <Input.Password placeholder={t("models.enterApiKeyOptional")} />
        </Form.Item>

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
                value: "OpenAIResponseModel",
                label: t("models.protocolOpenAIResponse"),
              },
              {
                value: "AnthropicChatModel",
                label: t("models.protocolAnthropic"),
              },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
