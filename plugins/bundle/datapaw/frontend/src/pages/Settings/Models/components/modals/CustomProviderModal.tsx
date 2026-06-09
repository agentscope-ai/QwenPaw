import { useState, useEffect } from "react";
import { Form, Input, Modal, Select } from "@agentscope-ai/design";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";

interface CustomProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function CustomProviderModal({
  open,
  onClose,
  onSaved,
}: CustomProviderModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    if (open) {
      form.resetFields();
    }
  }, [open, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await api.createCustomProvider({
        id: values.id.trim(),
        name: values.name.trim(),
        default_base_url: values.default_base_url?.trim() || "",
        api_key_prefix: values.api_key_prefix?.trim() || "",
        chat_model: values.chat_model || "OpenAIChatModel",
      });
      message.success(
        t("models.providerCreated", { name: values.name.trim() }),
      );
      onSaved();
      onClose();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.providerCreateFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("models.addProviderTitle")}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={saving}
      okText={t("common.create")}
      cancelText={t("models.cancel")}
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
          <Input placeholder={t("models.providerIdPlaceholder")} />
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
        >
          <Input placeholder={t("models.defaultBaseUrlPlaceholder")} />
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
