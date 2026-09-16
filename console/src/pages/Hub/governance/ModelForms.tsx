import { Form, Input, InputNumber, Select, Switch } from "antd";
import { ProviderConnectionFields } from "../../Settings/Models/components/modals/ProviderConnectionFields";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { getValidApiKeyPrefixes } from "../../Settings/Models/apiKeyValidation";
import { HubModelIdentityFields } from "./HubModelIdentityFields";
import type {
  ModelConnection,
  ModelProviderPreset,
} from "../../../api/modules/hubGovernance";
import styles from "./governance.module.less";
import { useGovernanceText } from "./shared";

export function ConnectionFields({
  connections,
  connectionId,
  independentScope,
  presets,
}: {
  connections: ModelConnection[];
  connectionId?: string;
  independentScope: string;
  presets: ModelProviderPreset[];
}) {
  const text = useGovernanceText();
  const form = Form.useFormInstance();
  const providerId = Form.useWatch("provider_id", form);
  const preset = presets.find((p) => p.id === providerId);

  const groups = new Map<string, string[]>();
  for (const connection of connections) {
    if (connection.id === connectionId) continue;
    const names = groups.get(connection.quota_scope) ?? [];
    names.push(connection.name);
    groups.set(connection.quota_scope, names);
  }
  return (
    <>
      <Form.Item name="provider_id" label={text("供应商", "Provider")}>
        <Select
          showSearch
          optionFilterProp="searchLabel"
          disabled={!!connectionId}
          onChange={(id) => {
            const selected = presets.find((p) => p.id === id);
            form.setFieldsValue({
              name: selected?.name ?? "",
              base_url: selected?.base_url ?? "",
              api_key: undefined,
            });
          }}
          options={[
            {
              value: "",
              label: text("自定义 · OpenAI 兼容", "Custom · OpenAI compatible"),
              searchLabel: "Custom 自定义",
            },
            ...presets.map((p) => ({
              value: p.id,
              searchLabel: p.name,
              label: (
                <span className={styles.actions}>
                  <ProviderIcon providerId={p.id} size={20} />
                  {p.name}
                </span>
              ),
            })),
          ]}
        />
      </Form.Item>
      <Form.Item
        name="name"
        label={text("连接名称", "Connection name")}
        rules={[{ required: true }]}
      >
        <Input maxLength={120} />
      </Form.Item>
      <ProviderConnectionFields
        canEditBaseUrl={!preset?.freeze_url}
        baseUrlOptions={preset?.base_url_options ?? []}
        baseUrlPlaceholder={preset?.base_url || "https://example.com/v1"}
        apiKeyLabel="API Key"
        apiKeyPlaceholder={
          connectionId
            ? text("留空保留已保存的密钥", "Leave blank to keep the saved key")
            : text("输入供应商 API Key", "Enter your provider API key")
        }
        validApiKeyPrefixes={preset ? getValidApiKeyPrefixes(preset) : []}
        requireApiKey={!connectionId}
      />
      <details className={styles.help}>
        <summary>{text("高级设置 · 限流", "Advanced · Rate limits")}</summary>
        <Form.Item
          name="quota_scope"
          label={text("与其他连接共享限流", "Share rate limits with")}
          extra={text(
            "仅在供应商对这些连接共用限额时选择。共享后合并计算请求量与并发数，按组内最低上限执行；不影响成员 Token 预算。",
            "Choose only when your provider shares limits across these connections. Requests and concurrency are counted together, using the lowest limits in the group. Member token budgets are unaffected.",
          )}
          rules={[{ required: true }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            options={[
              {
                value: independentScope,
                label: text("独立限流（默认）", "Independent limits (default)"),
              },
              ...Array.from(groups, ([value, names]) => ({
                value,
                label: names.join(" / "),
              })),
            ]}
          />
        </Form.Item>
        <RateFields />
      </details>
      <Form.Item
        name="enabled"
        label={text("启用", "Enabled")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
    </>
  );
}
export function RateFields() {
  const text = useGovernanceText();
  return (
    <>
      <Form.Item
        name="requests_per_minute"
        label={text("每分钟请求上限", "Requests per minute")}
        rules={[{ required: true }]}
      >
        <InputNumber min={1} max={100000} precision={0} />
      </Form.Item>
      <Form.Item
        name="concurrency"
        label={text("并发上限", "Concurrency")}
        rules={[{ required: true }]}
      >
        <InputNumber min={1} max={1000} precision={0} />
      </Form.Item>
    </>
  );
}
export function ModelFields({
  connections,
  users,
  presets,
}: {
  connections: ModelConnection[];
  users: { user_id: string; username: string }[];
  presets: ModelProviderPreset[];
}) {
  const text = useGovernanceText();
  return (
    <>
      <Form.Item
        name="connection_id"
        label={text("连接", "Connection")}
        rules={[{ required: true }]}
      >
        <Select
          options={connections.map((c) => ({ value: c.id, label: c.name }))}
        />
      </Form.Item>
      <HubModelIdentityFields connections={connections} presets={presets} />
      <Form.Item name="description" label={text("能力说明", "Description")}>
        <Input.TextArea maxLength={1000} />
      </Form.Item>
      <Form.Item
        name="input_token_limit"
        label={text(
          "已确认的最大输入 Token（用于保守预留）",
          "Verified maximum input tokens (reserved per request)",
        )}
        rules={[{ required: true }]}
      >
        <InputNumber min={1000} max={10000000} precision={0} />
      </Form.Item>
      <Form.Item
        name="output_token_limit"
        label={text("单次输出 Token 上限", "Maximum output tokens")}
        rules={[{ required: true }]}
      >
        <InputNumber min={1} max={1000000} precision={0} />
      </Form.Item>
      <Form.Item
        name="output_limit_field"
        label={text("上游输出限制参数", "Upstream output limit parameter")}
      >
        <Select
          options={[
            { value: "max_tokens" },
            { value: "max_completion_tokens" },
          ]}
        />
      </Form.Item>
      <Form.Item
        name="budget_verified"
        label={text(
          "已验证输入边界与输出上限（有限预算必需）",
          "Input and output bounds verified (required for finite budgets)",
        )}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="supports_image"
        label={text("支持图片输入", "Supports images")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="all_members"
        label={text("授权全体成员", "Available to all members")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="user_ids"
        label={text("或指定成员", "Or selected members")}
      >
        <Select
          mode="multiple"
          options={users.map((u) => ({ value: u.user_id, label: u.username }))}
        />
      </Form.Item>
      <details className={styles.help}>
        <summary>
          {text("速率与并发限制", "Rate and concurrency limits")}
        </summary>
        <RateFields />
      </details>
      <Form.Item
        name="enabled"
        label={text("发布启用", "Published and enabled")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
    </>
  );
}
