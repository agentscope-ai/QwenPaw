import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      <Form.Item name="provider_id" label={t("models.provider")}>
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
              label: t("hub.governance.models.customProvider"),
              searchLabel: t("hub.governance.models.customProvider"),
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
        label={t("hub.governance.models.connectionName")}
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
            ? t("hub.governance.models.keepKey")
            : t("hub.governance.models.enterKey")
        }
        validApiKeyPrefixes={preset ? getValidApiKeyPrefixes(preset) : []}
        requireApiKey={!connectionId}
      />
      <details className={styles.help}>
        <summary>{t("hub.governance.models.advancedLimits")}</summary>
        <Form.Item
          name="quota_scope"
          label={t("hub.governance.models.shareLimits")}
          extra={t("hub.governance.models.shareLimitsHint")}
          rules={[{ required: true }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            options={[
              {
                value: independentScope,
                label: t("hub.governance.models.independentLimits"),
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
        label={t("common.enabled")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
    </>
  );
}
export function RateFields() {
  const { t } = useTranslation();
  return (
    <>
      <Form.Item
        name="requests_per_minute"
        label={t("hub.governance.models.rpm")}
        rules={[{ required: true }]}
      >
        <InputNumber min={1} max={100000} precision={0} />
      </Form.Item>
      <Form.Item
        name="concurrency"
        label={t("hub.governance.models.concurrency")}
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
  const { t } = useTranslation();
  return (
    <>
      <Form.Item
        name="connection_id"
        label={t("hub.governance.models.connection")}
        rules={[{ required: true }]}
      >
        <Select
          options={connections.map((c) => ({ value: c.id, label: c.name }))}
        />
      </Form.Item>
      <HubModelIdentityFields connections={connections} presets={presets} />
      <Form.Item
        name="description"
        label={t("hub.governance.models.description")}
      >
        <Input.TextArea maxLength={1000} />
      </Form.Item>
      <Form.Item
        name="input_token_limit"
        label={t("hub.governance.models.inputLimit")}
        rules={[{ required: true }]}
      >
        <InputNumber min={1000} max={10000000} precision={0} />
      </Form.Item>
      <Form.Item
        name="output_token_limit"
        label={t("hub.governance.models.outputLimit")}
        rules={[{ required: true }]}
      >
        <InputNumber min={1} max={1000000} precision={0} />
      </Form.Item>
      <Form.Item
        name="output_limit_field"
        label={t("hub.governance.models.outputParameter")}
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
        label={t("hub.governance.models.boundsVerified")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="supports_image"
        label={t("hub.governance.models.supportsImages")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="all_members"
        label={t("hub.governance.models.allMembers")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="user_ids"
        label={t("hub.governance.models.selectedMembers")}
      >
        <Select
          mode="multiple"
          options={users.map((u) => ({ value: u.user_id, label: u.username }))}
        />
      </Form.Item>
      <details className={styles.help}>
        <summary>{t("hub.governance.models.rateLimits")}</summary>
        <RateFields />
      </details>
      <Form.Item
        name="enabled"
        label={t("hub.governance.models.published")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
    </>
  );
}
