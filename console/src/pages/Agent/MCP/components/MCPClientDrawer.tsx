import { Drawer, Form, Input, Switch, Button, Select } from "@agentscope-ai/design";
import type { MCPClientInfo, MCPTransport } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState } from "react";

interface MCPClientDrawerProps {
  open: boolean;
  client: MCPClientInfo | null;
  onClose: () => void;
  onSubmit: (
    key: string,
    values: {
      name: string;
      transport?: MCPTransport;
      command?: string;
      enabled?: boolean;
      args?: string[];
      env?: Record<string, string>;
      url?: string;
      headers?: Record<string, string>;
    },
  ) => Promise<boolean>;
  form: any;
}

// Validator for JSON object fields (env, headers)
const jsonObjectValidator = (_: unknown, value: string) => {
  if (!value || !value.trim()) return Promise.resolve();
  try {
    const parsed = JSON.parse(value);
    if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
      return Promise.reject(new Error("Must be a JSON object, e.g. {}"));
    }
    return Promise.resolve();
  } catch {
    return Promise.reject(new Error("Invalid JSON format"));
  }
};

export function MCPClientDrawer({
  open,
  client,
  onClose,
  onSubmit,
  form,
}: MCPClientDrawerProps) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState(false);
  const isEditing = !!client;

  const transport: MCPTransport = Form.useWatch("transport", form) ?? "stdio";

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const currentTransport: MCPTransport = values.transport ?? "stdio";

      const clientData: Record<string, unknown> = {
        name: values.name,
        enabled: values.enabled ?? true,
        transport: currentTransport,
      };

      if (currentTransport === "stdio") {
        clientData.command = values.command;
        clientData.args = values.args
          ? values.args.split(" ").filter(Boolean)
          : [];
        clientData.env = values.env ? JSON.parse(values.env) : {};
      } else {
        clientData.url = values.url;
        clientData.headers = values.headers
          ? JSON.parse(values.headers)
          : {};
      }

      const key = isEditing ? client.key : values.key;
      const success = await onSubmit(key, clientData as any);

      if (success) {
        onClose();
      }
    } catch (error) {
      console.error("Form validation failed:", error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      title={isEditing ? t("mcp.editClient") : t("mcp.createClient")}
      placement="right"
      onClose={onClose}
      open={open}
      width={600}
      footer={
        <div style={{ textAlign: "right" }}>
          <Button onClick={onClose} style={{ marginRight: 8 }}>
            {t("common.cancel")}
          </Button>
          <Button type="primary" onClick={handleSubmit} loading={submitting}>
            {isEditing ? t("common.save") : t("common.create")}
          </Button>
        </div>
      }
    >
      <Form form={form} layout="vertical">
        {!isEditing && (
          <Form.Item
            name="key"
            label={t("mcp.key")}
            rules={[{ required: true, message: t("mcp.keyRequired") }]}
          >
            <Input placeholder={t("mcp.keyPlaceholder")} />
          </Form.Item>
        )}

        <Form.Item
          name="name"
          label={t("mcp.name")}
          rules={[{ required: true, message: t("mcp.nameRequired") }]}
        >
          <Input placeholder={t("mcp.namePlaceholder")} />
        </Form.Item>

        <Form.Item name="description" label={t("mcp.description")}>
          <Input.TextArea
            rows={2}
            placeholder={t("mcp.descriptionPlaceholder")}
          />
        </Form.Item>

        <Form.Item
          name="transport"
          label={t("mcp.transport")}
          initialValue="stdio"
        >
          <Select>
            <Select.Option value="stdio">
              stdio ({t("mcp.transportStdioDesc")})
            </Select.Option>
            <Select.Option value="sse">
              SSE ({t("mcp.transportSseDesc")})
            </Select.Option>
            <Select.Option value="streamable_http">
              Streamable HTTP ({t("mcp.transportHttpDesc")})
            </Select.Option>
          </Select>
        </Form.Item>

        {/* stdio-specific fields */}
        {transport === "stdio" && (
          <>
            <Form.Item
              name="command"
              label={t("mcp.command")}
              rules={[
                { required: true, message: t("mcp.commandRequired") },
              ]}
            >
              <Input placeholder={t("mcp.commandPlaceholder")} />
            </Form.Item>

            <Form.Item
              name="args"
              label={t("mcp.args")}
              extra={t("mcp.argsHelp")}
            >
              <Input placeholder={t("mcp.argsPlaceholder")} />
            </Form.Item>

            <Form.Item
              name="env"
              label={t("mcp.env")}
              extra={t("mcp.envHelp")}
              rules={[{ validator: jsonObjectValidator }]}
            >
              <Input.TextArea
                rows={4}
                placeholder={t("mcp.envPlaceholder")}
              />
            </Form.Item>
          </>
        )}

        {/* SSE / Streamable HTTP fields */}
        {(transport === "sse" || transport === "streamable_http") && (
          <>
            <Form.Item
              name="url"
              label={t("mcp.url")}
              rules={[{ required: true, message: t("mcp.urlRequired") }]}
            >
              <Input placeholder={t("mcp.urlPlaceholder")} />
            </Form.Item>

            <Form.Item
              name="headers"
              label={t("mcp.headers")}
              extra={t("mcp.headersHelp")}
              rules={[{ validator: jsonObjectValidator }]}
            >
              <Input.TextArea
                rows={4}
                placeholder={t("mcp.headersPlaceholder")}
              />
            </Form.Item>
          </>
        )}

        <Form.Item
          name="enabled"
          label={t("mcp.enabled")}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
