import { Form, Input, InputNumber, Select, Switch } from "antd";
import type { ModelConnection } from "../../../api/modules/hubGovernance";
import styles from "./governance.module.less";
import { useGovernanceText } from "./shared";

export function ConnectionFields({
  connections,
  connectionId,
  independentScope,
}: {
  connections: ModelConnection[];
  connectionId?: string;
  independentScope: string;
}) {
  const text = useGovernanceText();
  const groups = new Map<string, string[]>();
  for (const connection of connections) {
    if (connection.id === connectionId) continue;
    const names = groups.get(connection.quota_scope) ?? [];
    names.push(connection.name);
    groups.set(connection.quota_scope, names);
  }
  return (
    <>
      <Form.Item
        name="name"
        label={text("连接名称", "Connection name")}
        rules={[{ required: true }]}
      >
        <Input maxLength={120} />
      </Form.Item>
      <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
        <Input placeholder="https://example.com/v1" />
      </Form.Item>
      <Form.Item
        name="api_key"
        label={text("API Key（留空保留原值）", "API key (leave empty to keep)")}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
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
}: {
  connections: ModelConnection[];
  users: { user_id: string; username: string }[];
}) {
  const text = useGovernanceText();
  return (
    <>
      <Form.Item
        name="name"
        label={text("成员看到的名称", "Display name")}
        rules={[{ required: true }]}
      >
        <Input maxLength={120} />
      </Form.Item>
      <Form.Item name="description" label={text("能力说明", "Description")}>
        <Input.TextArea maxLength={1000} />
      </Form.Item>
      <Form.Item
        name="connection_id"
        label={text("连接", "Connection")}
        rules={[{ required: true }]}
      >
        <Select
          options={connections.map((c) => ({ value: c.id, label: c.name }))}
        />
      </Form.Item>
      <Form.Item
        name="upstream_model"
        label={text("上游模型 ID", "Upstream model ID")}
        rules={[{ required: true }]}
      >
        <Input maxLength={256} />
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
