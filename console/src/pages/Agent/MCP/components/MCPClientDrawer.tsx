import { Drawer, Form, Input, Switch, Button } from "@agentscope-ai/design";
import type { MCPClientInfo } from "../../../../api/types";
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
      command?: string;
      enabled?: boolean;
      transport?: "stdio" | "streamable_http" | "sse";
      url?: string;
      headers?: Record<string, string>;
      args?: string[];
      env?: Record<string, string>;
      cwd?: string;
    },
  ) => Promise<boolean>;
  form: any;
}

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

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const clientData = {
        name: values.name,
        command: values.command,
        enabled: values.enabled ?? true,
        args: values.args ? values.args.split(" ").filter(Boolean) : [],
        env: values.env ? JSON.parse(values.env) : {},
      };

      const key = isEditing ? client.key : values.key;
      const success = await onSubmit(key, clientData);

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
          name="command"
          label={t("mcp.command")}
          rules={[{ required: true, message: t("mcp.commandRequired") }]}
        >
          <Input placeholder={t("mcp.commandPlaceholder")} />
        </Form.Item>

        <Form.Item name="args" label={t("mcp.args")} extra={t("mcp.argsHelp")}>
          <Input placeholder={t("mcp.argsPlaceholder")} />
        </Form.Item>

        <Form.Item name="env" label={t("mcp.env")} extra={t("mcp.envHelp")}>
          <Input.TextArea rows={4} placeholder={t("mcp.envPlaceholder")} />
        </Form.Item>

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
