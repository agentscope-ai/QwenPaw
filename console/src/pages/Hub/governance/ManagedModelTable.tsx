import { useMemo, useState } from "react";
import { Button, Input, Select, Switch, Table, Tag, Tooltip } from "antd";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  ManagedModel,
  ModelConnection,
} from "../../../api/modules/hubGovernance";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { formatTokens } from "./budgetUtils";
import styles from "./ManagedModelTable.module.less";

export default function ManagedModelTable({
  models,
  connections,
  defaultModel,
  updatingItem,
  onConfigure,
  onToggle,
  onTest,
}: {
  models: ManagedModel[];
  connections: ModelConnection[];
  defaultModel: string | null;
  updatingItem?: string;
  onConfigure: (model: ManagedModel) => void;
  onToggle: (model: ManagedModel, enabled: boolean) => void;
  onTest: (model: ManagedModel) => Promise<void>;
}) {
  const { t, i18n } = useTranslation();
  const [search, setSearch] = useState("");
  const [provider, setProvider] = useState<string>();
  const [enabled, setEnabled] = useState<string>();
  const [page, setPage] = useState(1);
  const [testing, setTesting] = useState<string>();
  const providers = new Map(connections.map((c) => [c.id, c]));
  const rows = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return models.filter(
      (m) =>
        (!provider || m.connection_id === provider) &&
        (enabled === undefined || m.enabled === (enabled === "enabled")) &&
        (!query ||
          `${m.name} ${m.upstream_model}`.toLocaleLowerCase().includes(query)),
    );
  }, [models, search, provider, enabled]);
  return (
    <div className={styles.catalog}>
      <div className={styles.filters}>
        <Input
          allowClear
          prefix={<Search size={15} />}
          placeholder={t("modelSelector.searchModels")}
          aria-label={t("modelSelector.searchModels")}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder={t("models.provider")}
          aria-label={t("models.provider")}
          value={provider}
          onChange={(value) => {
            setProvider(value);
            setPage(1);
          }}
          options={connections.map((c) => ({ value: c.id, label: c.name }))}
        />
        <Select
          allowClear
          placeholder={t("hub.table.status")}
          aria-label={t("hub.table.status")}
          value={enabled}
          onChange={(value) => {
            setEnabled(value);
            setPage(1);
          }}
          options={[
            { value: "enabled", label: t("common.enabled") },
            { value: "disabled", label: t("common.disabled") },
          ]}
        />
      </div>
      <Table<ManagedModel>
        size="small"
        rowKey="id"
        dataSource={rows}
        scroll={{ x: 980 }}
        pagination={{
          current: page,
          pageSize: 15,
          showSizeChanger: false,
          onChange: setPage,
          hideOnSinglePage: true,
        }}
        columns={[
          {
            title: t("tokenUsage.model"),
            key: "model",
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, m) => (
              <div className={styles.identity}>
                <div>
                  <button
                    className={styles.modelName}
                    onClick={() => onConfigure(m)}
                  >
                    {m.name}
                  </button>
                  {defaultModel === m.id && (
                    <Tag bordered={false} color="orange">
                      {t("hub.governance.models.default")}
                    </Tag>
                  )}
                </div>
                {m.upstream_model !== m.name && (
                  <small>{m.upstream_model}</small>
                )}
              </div>
            ),
          },
          {
            title: t("models.provider"),
            key: "provider",
            width: 190,
            render: (_, m) => {
              const c = providers.get(m.connection_id);
              return (
                <div className={styles.provider}>
                  <ProviderIcon
                    providerId={c?.provider_id || c?.name || m.name}
                    size={20}
                  />
                  <span>{c?.name}</span>
                  {!c?.enabled && (
                    <Tooltip
                      title={t("hub.governance.models.connectionDisabled")}
                    >
                      <span
                        className={styles.disabledDot}
                        role="img"
                        aria-label={t(
                          "hub.governance.models.connectionDisabled",
                        )}
                      />
                    </Tooltip>
                  )}
                </div>
              );
            },
          },
          {
            title: t("models.maxInputLengthLabel"),
            dataIndex: "input_token_limit",
            width: 120,
            render: (value: number) => (
              <span title={value.toLocaleString(i18n.language)}>
                {formatTokens(value, i18n.language)}
              </span>
            ),
          },
          {
            title: t("models.maxTokensLabel"),
            dataIndex: "output_token_limit",
            width: 120,
            render: (value: number) => (
              <span title={value.toLocaleString(i18n.language)}>
                {formatTokens(value, i18n.language)}
              </span>
            ),
          },
          {
            title: t("hub.governance.models.access"),
            key: "access",
            width: 130,
            render: (_, m) =>
              m.all_members
                ? t("hub.governance.models.allMembersLabel")
                : t("hub.governance.models.memberCount", {
                    count: m.user_ids.length,
                  }),
          },
          {
            title: t("common.enabled"),
            key: "enabled",
            width: 75,
            render: (_, m) => (
              <Switch
                size="small"
                checked={m.enabled}
                loading={updatingItem === `model:${m.id}`}
                disabled={!!updatingItem && updatingItem !== `model:${m.id}`}
                aria-label={t("hub.governance.models.toggleModel", {
                  name: m.name,
                })}
                onChange={(value) => onToggle(m, value)}
              />
            ),
          },
          {
            title: "",
            key: "actions",
            width: 185,
            render: (_, m) => (
              <div className={styles.actions}>
                <Button type="text" size="small" onClick={() => onConfigure(m)}>
                  {t("hub.governance.models.configure")}
                </Button>
                <Button
                  type="text"
                  size="small"
                  loading={testing === m.id}
                  disabled={
                    !m.enabled ||
                    !providers.get(m.connection_id)?.enabled ||
                    (!!testing && testing !== m.id)
                  }
                  onClick={async () => {
                    setTesting(m.id);
                    try {
                      await onTest(m);
                    } finally {
                      setTesting(undefined);
                    }
                  }}
                >
                  {t("hub.governance.models.testConnection")}
                </Button>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
