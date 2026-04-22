import {
  Drawer,
  Form,
  Input,
  Switch,
  Button,
  Select,
  InputNumber,
} from "@agentscope-ai/design";
import type { FormInstance } from "antd";
import { useTranslation } from "react-i18next";
import {
  ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
  type ACPAgentConfig,
  type ACPToolParseMode,
} from "../../../../api/types";

interface ACPDrawerProps {
  open: boolean;
  activeKey: string | null;
  isCreateMode?: boolean;
  form: FormInstance<Record<string, unknown>>;
  saving: boolean;
  initialValues?: ACPAgentConfig;
  onClose: () => void;
  onSubmit: (values: Record<string, unknown>) => void;
}

const TOOL_PARSE_MODE_OPTIONS: { value: ACPToolParseMode; label: string }[] = [
  { value: "call_title", label: "call_title" },
  { value: "update_detail", label: "update_detail" },
  { value: "call_detail", label: "call_detail" },
];

export function parseArgsText(value: unknown): string[] {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseEnvText(value: unknown): Record<string, string> {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, line) => {
      const index = line.indexOf("=");
      if (index >= 0) {
        const key = line.slice(0, index).trim();
        const envValue = line.slice(index + 1).trim();
        if (key) acc[key] = envValue;
      }
      return acc;
    }, {});
}

function findInvalidEnvLine(value: unknown): string | null {
  const lines = String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  for (const line of lines) {
    const index = line.indexOf("=");
    if (index <= 0 || !line.slice(0, index).trim()) {
      return line;
    }
  }
  return null;
}

export function stringifyArgs(args: string[] = []): string {
  return args.join("\n");
}

export function stringifyEnv(env: Record<string, string> = {}): string {
  return Object.entries(env)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

export function ACPDrawer({
  open,
  activeKey,
  isCreateMode = false,
  form,
  saving,
  initialValues,
  onClose,
  onSubmit,
}: ACPDrawerProps) {
  const { t } = useTranslation();

  return (
    <Drawer
      title={
        isCreateMode
          ? t("acp.createTitle")
          : activeKey
            ? `${t("acp.editTitle")}: ${activeKey}`
            : t("acp.editTitle")
      }
      open={open}
      onClose={onClose}
      width={520}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" loading={saving} onClick={() => form.submit()}>
            {t("common.save")}
          </Button>
        </div>
      }
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={onSubmit}
      >
        <Form.Item
          name="agentKey"
          label={t("acp.agentKey")}
          hidden={!isCreateMode}
          rules={
            isCreateMode
              ? [
                  { required: true, message: t("acp.agentKeyRequired") },
                  {
                    pattern: /^[A-Za-z0-9_-]+$/,
                    message: t("acp.agentKeyInvalid"),
                  },
                ]
              : []
          }
        >
          <Input placeholder="my_custom_runner" />
        </Form.Item>

        <Form.Item
          name="enabled"
          label={t("acp.enabled")}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="command"
          label={t("acp.command")}
          rules={[{ required: true, message: t("acp.commandRequired") }]}
        >
          <Input placeholder="qwen" />
        </Form.Item>

        <Form.Item
          name="argsText"
          label={t("acp.args")}
          tooltip={t("acp.argsHelp")}
        >
          <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} />
        </Form.Item>

        <Form.Item
          name="envText"
          label={t("acp.env")}
          tooltip={t("acp.envHelp")}
          rules={[
            {
              validator: async (_, value) => {
                const invalidLine = findInvalidEnvLine(value);
                if (invalidLine) {
                  throw new Error(
                    t("acp.envInvalidLine", { line: invalidLine }),
                  );
                }
              },
            },
          ]}
        >
          <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} />
        </Form.Item>

        <Form.Item
          name="trusted"
          label={t("acp.trusted")}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="tool_parse_mode"
          label={t("acp.toolParseMode")}
          rules={[{ required: true, message: t("acp.toolParseModeRequired") }]}
        >
          <Select options={TOOL_PARSE_MODE_OPTIONS} />
        </Form.Item>

        <Form.Item
          name="stdio_buffer_limit_bytes"
          label={t("acp.stdioBufferLimit")}
          tooltip={t("acp.stdioBufferLimitHelp")}
          rules={[
            {
              required: true,
              message: t("acp.stdioBufferLimitRequired"),
            },
            {
              type: "number",
              min: 1,
              message: t("acp.stdioBufferLimitMin"),
            },
          ]}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={1024}
            placeholder={String(ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES)}
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
