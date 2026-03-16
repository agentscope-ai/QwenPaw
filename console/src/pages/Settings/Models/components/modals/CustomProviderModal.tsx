import { useState, useEffect } from "react";
import {
  Form,
  Input,
  Modal,
  Select,
  message,
  Button,
} from "@agentscope-ai/design";
import { Space } from "antd";
import {
  PlusOutlined,
  DeleteOutlined,
  DownOutlined,
  RightOutlined,
} from "@ant-design/icons";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";

interface HeaderItem {
  key: string;
  value: string;
}

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
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const [headers, setHeaders] = useState<HeaderItem[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
      setHeaders([]);
      setAdvancedOpen(false);
    }
  }, [open, form]);

  const addHeader = () => {
    // Pre-fill User-Agent for the first header (common for Kimi Coding Plan)
    const newHeader =
      headers.length === 0
        ? { key: "User-Agent", value: "" }
        : { key: "", value: "" };
    setHeaders([...headers, newHeader]);
  };

  const removeHeader = (index: number) => {
    setHeaders(headers.filter((_, i) => i !== index));
  };

  const updateHeader = (
    index: number,
    field: keyof HeaderItem,
    value: string,
  ) => {
    const newHeaders = [...headers];
    newHeaders[index][field] = value;
    setHeaders(newHeaders);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      // Convert headers array to object
      const defaultHeaders: Record<string, string> = {};
      headers.forEach(({ key, value }) => {
        if (key.trim()) {
          defaultHeaders[key.trim()] = value;
        }
      });

      await api.createCustomProvider({
        id: values.id.trim(),
        name: values.name.trim(),
        default_base_url: values.default_base_url?.trim() || "",
        api_key_prefix: values.api_key_prefix?.trim() || "",
        chat_model: values.chat_model || "OpenAIChatModel",
        default_headers: defaultHeaders,
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

        {/* Advanced Config - Headers */}
        <div style={{ marginTop: 16 }}>
          <button
            type="button"
            onClick={() => setAdvancedOpen(!advancedOpen)}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
              fontSize: 14,
              color: "#666",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {advancedOpen ? <DownOutlined /> : <RightOutlined />}
            {t("models.advancedConfig", "Advanced Config")}
          </button>

          {advancedOpen && (
            <div style={{ marginTop: 12 }}>
              <div style={{ marginBottom: 8, fontSize: 14, color: "#333" }}>
                {t("models.customHeaders", "Custom Headers")}
              </div>
              {headers.map((header, index) => (
                <Space
                  key={index}
                  style={{ display: "flex", marginBottom: 8 }}
                  align="baseline"
                >
                  <Input
                    placeholder="Header Key (e.g. User-Agent)"
                    value={header.key}
                    onChange={(e) => updateHeader(index, "key", e.target.value)}
                    style={{ width: 200 }}
                  />
                  <Input
                    placeholder="Header Value"
                    value={header.value}
                    onChange={(e) =>
                      updateHeader(index, "value", e.target.value)
                    }
                    style={{ width: 200 }}
                  />
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removeHeader(index)}
                  />
                </Space>
              ))}
              <Button
                type="dashed"
                onClick={addHeader}
                icon={<PlusOutlined />}
                size="small"
              >
                {t("models.addHeader", "Add Header")}
              </Button>
              <div style={{ marginTop: 8, fontSize: 12, color: "#888" }}>
                {t(
                  "models.headersHint",
                  "Optional: Add custom HTTP headers for API requests. Example: User-Agent: KimiCLI/0.77",
                )}
              </div>
            </div>
          )}
        </div>
      </Form>
    </Modal>
  );
}
