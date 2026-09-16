import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Form, Input, InputNumber, Select, Switch } from "antd";
import { ProviderConnectionFields } from "../../Settings/Models/components/modals/ProviderConnectionFields";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { getValidApiKeyPrefixes } from "../../Settings/Models/apiKeyValidation";
import { HubModelIdentityFields } from "./HubModelIdentityFields";
import type {
  ManagedModel,
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
            const baseName = selected?.name ?? "";
            let name = baseName;
            let suffix = 2;
            while (name && connections.some((c) => c.name === name)) {
              name = `${baseName} ${suffix++}`;
            }
            form.setFieldsValue({
              name,
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
        tooltip={{
          title: t("hub.governance.models.zeroUnlimited"),
          icon: <CircleHelp size={14} />,
        }}
        rules={[{ required: true }]}
      >
        <InputNumber min={0} max={100000} precision={0} />
      </Form.Item>
      <Form.Item
        name="concurrency"
        label={t("hub.governance.models.concurrency")}
        tooltip={{
          title: t("hub.governance.models.zeroUnlimited"),
          icon: <CircleHelp size={14} />,
        }}
        rules={[{ required: true }]}
      >
        <InputNumber min={0} max={1000} precision={0} />
      </Form.Item>
    </>
  );
}
export function ModelFields({
  connections,
  users,
  presets,
  saved,
}: {
  connections: ModelConnection[];
  users: { user_id: string; username: string }[];
  presets: ModelProviderPreset[];
  saved?: ManagedModel;
}) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const allMembers = Form.useWatch("all_members", form);
  return (
    <>
      <section className={styles.formSection}>
        <h3>{t("hub.governance.models.modelSection")}</h3>
        <Form.Item
          name="connection_id"
          label={t("models.provider")}
          rules={[{ required: true }]}
        >
          <Select
            showSearch
            optionFilterProp="searchLabel"
            onChange={() =>
              form.setFieldsValue({
                upstream_model: undefined,
                name: undefined,
              })
            }
            options={connections.map((c) => ({
              value: c.id,
              searchLabel: c.name,
              label: (
                <span className={styles.actions}>
                  <ProviderIcon
                    key={c.provider_id ?? c.id}
                    providerId={c.provider_id || c.name}
                    size={20}
                  />
                  {c.name}
                </span>
              ),
            }))}
          />
        </Form.Item>
        <HubModelIdentityFields
          connections={connections}
          presets={presets}
          saved={saved}
        />
      </section>
      <section className={styles.formSection}>
        <h3>{t("hub.governance.users.modelAccess")}</h3>
        <div className={styles.permissionRow}>
          <span>{t("hub.governance.models.allMembers")}</span>
          <Form.Item name="all_members" valuePropName="checked" noStyle>
            <Switch aria-label={t("hub.governance.models.allMembers")} />
          </Form.Item>
        </div>
        {!allMembers && (
          <Form.Item
            name="user_ids"
            label={t("hub.governance.models.selectedMembers")}
          >
            <Select
              mode="multiple"
              options={users.map((u) => ({
                value: u.user_id,
                label: u.username,
              }))}
            />
          </Form.Item>
        )}
      </section>
      <details className={styles.advancedSettings}>
        <summary>{t("hub.governance.models.advancedSettings")}</summary>
        <RateFields />
      </details>
    </>
  );
}
