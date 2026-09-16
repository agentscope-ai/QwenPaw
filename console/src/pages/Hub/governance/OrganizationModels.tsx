import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useState, useRef } from "react";
import {
  App,
  Button,
  Form,
  Modal,
  Select,
  Switch,
  Tabs,
  Skeleton,
  Tag,
} from "antd";
import {
  Edit3,
  Plus,
  RefreshCw,
  Boxes,
  Plug,
  ArrowRight,
  X,
} from "lucide-react";
import {
  governanceRequest as request,
  type ModelPolicy,
  type ModelConnection,
  type ModelProviderPreset,
  type ManagedModel,
  type UsageReport,
} from "../../../api/modules/hubGovernance";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { ConnectionFields, ModelFields } from "./ModelForms";
import { editable } from "./shared";
import { governanceErrorMessage } from "./errors";
import ModelUsage from "./ModelUsage";
import styles from "./governance.module.less";

export default function OrganizationModels({
  initialModel,
}: {
  initialModel?: string;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [policy, setPolicy] = useState<ModelPolicy>();
  const [connections, setConnections] = useState<ModelConnection[]>([]);
  const [presets, setPresets] = useState<ModelProviderPreset[]>([]);
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [users, setUsers] = useState<UsageReport["members"]>([]);
  const [editing, setEditing] = useState<{
    type: "connection" | "model";
    id?: string;
    revision?: number;
  }>();
  const [independentScope, setIndependentScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [updatingItem, setUpdatingItem] = useState<string>();
  const [tab, setTab] = useState(initialModel === "usage" ? "usage" : "models");
  const [error, setError] = useState("");
  const [form] = Form.useForm();
  const [policyForm] = Form.useForm();
  const load = useCallback(async () => {
    try {
      const [p, c, m, u, presets] = await Promise.all([
        request<ModelPolicy>("admin/model-policy"),
        request<ModelConnection[]>("admin/model-connections"),
        request<ManagedModel[]>("admin/models"),
        request<UsageReport>("admin/usage"),
        request<ModelProviderPreset[]>("admin/model-provider-presets"),
      ]);
      setPresets(presets);
      setPolicy(p);
      setError("");
      setConnections(c);
      setModels(m);
      setUsers(u.members);
      if (m.length) policyForm.setFieldsValue(p);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [policyForm]);
  useEffect(() => {
    void load();
  }, [load]);
  const open = (
    type: "connection" | "model",
    value?: ModelConnection | ManagedModel,
    connectionId?: string,
  ) => {
    form.resetFields();
    if (type === "connection") {
      const connection = value as ModelConnection | undefined;
      const sharesQuota = connections.some(
        (other) =>
          other.id !== connection?.id &&
          other.quota_scope === connection?.quota_scope,
      );
      const scope =
        connection && !sharesQuota
          ? connection.quota_scope
          : Array.from(crypto.getRandomValues(new Uint32Array(4)), (part) =>
              part.toString(16).padStart(8, "0"),
            ).join("");
      setIndependentScope(scope);
      form.setFieldValue("quota_scope", scope);
      form.setFieldValue("provider_id", connection?.provider_id ?? "");
    }
    if (value) {
      const data = editable(value);
      if ("has_key" in data) delete data.has_key;
      form.setFieldsValue(data);
      if (type === "connection")
        form.setFieldValue(
          "provider_id",
          (value as ModelConnection).provider_id ?? "",
        );
    } else
      form.setFieldsValue(
        type === "connection"
          ? { enabled: true, requests_per_minute: 0, concurrency: 0 }
          : {
              connection_id: connectionId ?? connections[0]?.id,
              description: "",
              enabled: true,
              all_members: true,
              user_ids: [],
              output_limit_field: "max_tokens",
              requests_per_minute: 0,
              concurrency: 0,
            },
      );
    setEditing({ type, id: value?.id, revision: value?.revision });
  };
  const connectionById = new Map(
    connections.map((connection) => [connection.id, connection]),
  );
  const availableModels = models.filter(
    (model) =>
      model.enabled && connectionById.get(model.connection_id)?.enabled,
  );
  const updateEnabled = async (
    type: "connection" | "model",
    item: ModelConnection | ManagedModel,
    enabled: boolean,
  ) => {
    const affectsDefault =
      type === "model"
        ? policy?.default_model_id === item.id
        : models.some(
            (m) =>
              m.id === policy?.default_model_id && m.connection_id === item.id,
          );
    if (!enabled && affectsDefault) {
      message.warning(t("hub.governance.models.changeDefaultFirst"));
      return;
    }
    setUpdatingItem(`${type}:${item.id}`);
    try {
      const { id, ...body } = item;
      if ("has_key" in body) delete (body as Partial<ModelConnection>).has_key;
      const resource = type === "connection" ? "model-connections" : "models";
      await request(`admin/${resource}/${id}`, "PUT", { ...body, enabled });
      await load();
    } catch (e) {
      message.error(governanceErrorMessage(e, t));
    } finally {
      setUpdatingItem(undefined);
    }
  };
  const openedInitial = useRef<string>();
  useEffect(() => {
    if (initialModel === "usage") setTab("usage");
  }, [initialModel]);
  useEffect(() => {
    if (
      !initialModel ||
      initialModel === "usage" ||
      openedInitial.current === initialModel
    )
      return;
    const found = models.find((model) => model.id === initialModel);
    if (found) {
      openedInitial.current = initialModel;
      open("model", found);
    }
  });
  return (
    <div className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <span className={styles.eyebrow}>
            {t("hub.governance.models.eyebrow")}
          </span>
          <h2>{t("hub.governance.models.title")}</h2>
        </div>
        {tab !== "usage" && (
          <div className={styles.actions}>
            <Button
              aria-label={t("common.refresh")}
              icon={<RefreshCw size={15} />}
              onClick={load}
            />
            <Button
              type="primary"
              icon={<Plus size={15} />}
              onClick={() =>
                open(
                  tab === "connections" || !connections.length
                    ? "connection"
                    : "model",
                )
              }
            >
              {tab === "connections" || !connections.length
                ? t("hub.governance.models.addProvider")
                : t("hub.governance.models.addModel")}
            </Button>
          </div>
        )}
      </div>
      {error && (
        <div role="alert" className={styles.notice}>
          {governanceErrorMessage(error, t)}
          <Button onClick={load}>{t("common.retry")}</Button>
        </div>
      )}
      {!policy && !error && <Skeleton active />}
      {policy && (
        <>
          {tab !== "usage" && (
            <div className={styles.serviceStrip}>
              <span className={styles.serviceIcon}>
                <Boxes size={20} />
              </span>
              <div>
                <strong>{t("hub.governance.models.organizationTitle")}</strong>
              </div>
              <Tag
                bordered={false}
                color={availableModels.length > 0 ? "success" : "default"}
              >
                {availableModels.length > 0
                  ? t("hub.runtimes.available")
                  : t("hub.governance.models.setup")}
              </Tag>
            </div>
          )}
          <Tabs
            className={styles.modelTabs}
            activeKey={tab}
            onChange={setTab}
            items={[
              {
                key: "models",
                label: t("hub.governance.models.availableModels"),
                children: (
                  <div className={styles.panel}>
                    {!models.length ? (
                      <div className={styles.onboarding}>
                        <Boxes size={32} />
                        <h3>{t("hub.governance.models.emptyTitle")}</h3>
                        <Button
                          type="primary"
                          icon={<ArrowRight size={15} />}
                          onClick={() =>
                            open(connections.length ? "model" : "connection")
                          }
                        >
                          {connections.length
                            ? t("hub.governance.models.firstModel")
                            : t("hub.governance.models.connectProvider")}
                        </Button>
                      </div>
                    ) : (
                      <div className={styles.grid}>
                        {models.map((m) => (
                          <article key={m.id} className={styles.card}>
                            <div className={styles.heading}>
                              <ProviderIcon
                                providerId={
                                  connectionById.get(m.connection_id)
                                    ?.provider_id ||
                                  connectionById.get(m.connection_id)?.name ||
                                  m.name
                                }
                                size={36}
                              />
                              <div className={styles.connectionToggle}>
                                <span>
                                  {t(
                                    m.enabled
                                      ? "hub.governance.models.modelEnabled"
                                      : "hub.governance.models.modelDisabled",
                                  )}
                                </span>
                                <Switch
                                  size="small"
                                  checked={m.enabled}
                                  loading={updatingItem === `model:${m.id}`}
                                  disabled={
                                    !!updatingItem &&
                                    updatingItem !== `model:${m.id}`
                                  }
                                  aria-label={t(
                                    "hub.governance.models.toggleModel",
                                    { name: m.name },
                                  )}
                                  onChange={(enabled) =>
                                    updateEnabled("model", m, enabled)
                                  }
                                />
                              </div>
                            </div>
                            <h3>
                              {m.name}{" "}
                              {policy.default_model_id === m.id && (
                                <Tag bordered={false} color="orange">
                                  {t("hub.governance.models.default")}
                                </Tag>
                              )}
                            </h3>
                            <p>
                              {m.description ||
                                connectionById.get(m.connection_id)?.name}
                            </p>
                            {!connectionById.get(m.connection_id)?.enabled && (
                              <p className={styles.muted}>
                                {t("hub.governance.models.connectionDisabled")}
                              </p>
                            )}
                            <div className={styles.detailRow}>
                              <span>{t("hub.governance.models.access")}</span>
                              <strong>
                                {m.all_members
                                  ? t("hub.governance.models.allMembersLabel")
                                  : t("hub.governance.models.memberCount", {
                                      count: m.user_ids.length,
                                    })}
                              </strong>
                            </div>
                            <div className={styles.actions}>
                              <Button onClick={() => open("model", m)}>
                                {t("hub.governance.models.configure")}
                              </Button>
                              <Button
                                disabled={
                                  !connectionById.get(m.connection_id)?.enabled
                                }
                                title={
                                  !connectionById.get(m.connection_id)?.enabled
                                    ? t(
                                        "hub.governance.errors.connectionDisabled",
                                      )
                                    : undefined
                                }
                                onClick={async () => {
                                  try {
                                    await request(
                                      `admin/models/${m.id}/test`,
                                      "POST",
                                    );
                                    message.success(
                                      t(
                                        "hub.governance.models.connectionSucceeded",
                                      ),
                                    );
                                  } catch (e) {
                                    message.error(governanceErrorMessage(e, t));
                                  }
                                }}
                              >
                                {t("hub.governance.models.testConnection")}
                              </Button>
                              {!connectionById.get(m.connection_id)?.enabled &&
                                connectionById.has(m.connection_id) && (
                                  <Button onClick={() => setTab("connections")}>
                                    {t("hub.governance.models.viewProvider")}
                                  </Button>
                                )}
                            </div>
                          </article>
                        ))}
                      </div>
                    )}
                    {!!models.length && (
                      <article className={styles.card}>
                        <div className={styles.heading}>
                          <div>
                            <h3>{t("hub.governance.models.memberDefaults")}</h3>
                          </div>
                        </div>
                        <Form
                          form={policyForm}
                          layout="vertical"
                          className={styles.form}
                          onFinish={async (values) => {
                            setBusy(true);
                            try {
                              const next = await request<ModelPolicy>(
                                "admin/model-policy",
                                "PUT",
                                {
                                  ...policy,
                                  ...values,
                                  default_model_id:
                                    values.default_model_id ?? null,
                                },
                              );
                              setPolicy(next);
                              policyForm.setFieldsValue(next);
                              message.success(
                                t("hub.governance.models.settingsSaved"),
                              );
                            } catch (e) {
                              message.error(governanceErrorMessage(e, t));
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          <Form.Item
                            name="default_model_id"
                            label={t("hub.governance.models.defaultModel")}
                          >
                            <Select
                              placeholder={t(
                                "hub.governance.models.chooseDefault",
                              )}
                              options={availableModels
                                .filter((m) => m.all_members)
                                .map((m) => ({
                                  value: m.id,
                                  label: `${m.name} · ${
                                    connectionById.get(m.connection_id)?.name ??
                                    ""
                                  }`,
                                }))}
                            />
                          </Form.Item>
                          <Button
                            type="primary"
                            htmlType="submit"
                            loading={busy}
                          >
                            {t("hub.governance.models.saveSettings")}
                          </Button>
                        </Form>
                      </article>
                    )}
                  </div>
                ),
              },
              {
                key: "connections",
                label: t("hub.governance.models.providers"),
                children: (
                  <div className={styles.panel}>
                    {connections.length ? (
                      <div className={styles.grid}>
                        {connections.map((c) => (
                          <article className={styles.card} key={c.id}>
                            <div className={styles.heading}>
                              <ProviderIcon
                                providerId={c.provider_id || c.name}
                                size={40}
                              />
                              <div className={styles.connectionToggle}>
                                <span>
                                  {t(
                                    c.enabled
                                      ? "hub.governance.models.providerEnabled"
                                      : "hub.governance.models.connectionDisabled",
                                  )}
                                </span>
                                <Switch
                                  size="small"
                                  checked={c.enabled}
                                  loading={
                                    updatingItem === `connection:${c.id}`
                                  }
                                  disabled={
                                    !!updatingItem &&
                                    updatingItem !== `connection:${c.id}`
                                  }
                                  aria-label={t(
                                    "hub.governance.models.toggleProvider",
                                    { name: c.name },
                                  )}
                                  onChange={(enabled) =>
                                    updateEnabled("connection", c, enabled)
                                  }
                                />
                              </div>
                            </div>
                            <h3>{c.name}</h3>
                            <p
                              className={styles.connectionUrl}
                              title={c.base_url}
                            >
                              {c.base_url}
                            </p>
                            <div className={styles.detailRow}>
                              <span>API Key</span>
                              <strong>
                                {c.has_key
                                  ? t("hub.governance.models.keyStored")
                                  : t("hub.governance.models.keyMissing")}
                              </strong>
                            </div>
                            <div className={styles.actions}>
                              <Button
                                icon={<Edit3 size={14} />}
                                onClick={() => open("connection", c)}
                              >
                                {t("hub.governance.models.manageConnection")}
                              </Button>
                              <Button
                                onClick={() => open("model", undefined, c.id)}
                              >
                                {t("hub.governance.models.addModel")}
                              </Button>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <div className={styles.empty}>
                        <Plug size={28} />
                        <strong>
                          {t("hub.governance.models.noProviders")}
                        </strong>
                      </div>
                    )}
                  </div>
                ),
              },
              {
                key: "usage",
                label: t("hub.governance.analytics.usage"),
                children: <ModelUsage />,
              },
            ]}
          />
        </>
      )}
      <Modal
        open={!!editing}
        centered
        destroyOnHidden
        afterClose={() => form.resetFields()}
        okText={t("common.save")}
        title={
          editing?.type === "connection"
            ? t("hub.governance.models.connectionTitle")
            : t("hub.governance.models.modelTitle")
        }
        closeIcon={<X size={18} />}
        width={640}
        onCancel={() => setEditing(undefined)}
        onOk={() => form.submit()}
        confirmLoading={busy}
      >
        <Form
          form={form}
          key={`${editing?.type}:${editing?.id ?? "new"}`}
          layout="vertical"
          className={styles.form}
          onFinishFailed={({ errorFields }) =>
            message.error(errorFields[0]?.errors[0])
          }
          onFinish={async (values) => {
            if (!editing) return;
            setBusy(true);
            try {
              const body = { ...values, revision: editing.revision };
              if (editing.type === "connection") {
                if (!body.api_key) delete body.api_key;
                body.provider_id = body.provider_id || null;
                body.enabled = editing.id
                  ? connections.find((c) => c.id === editing.id)?.enabled ??
                    true
                  : true;
              } else {
                body.name = body.name?.trim() || body.upstream_model?.trim();
                body.budget_verified = true;
                body.enabled = editing.id
                  ? models.find((m) => m.id === editing.id)?.enabled ?? true
                  : true;
                if (body.all_members) body.user_ids = [];
              }
              const path =
                editing.type === "connection"
                  ? "admin/model-connections"
                  : "admin/models";
              await request(
                editing.id ? `${path}/${editing.id}` : path,
                editing.id ? "PUT" : "POST",
                body,
              );
              setEditing(undefined);
              form.resetFields();
              await load();
            } catch (e) {
              message.error(governanceErrorMessage(e, t));
            } finally {
              setBusy(false);
            }
          }}
        >
          {editing?.type === "connection" ? (
            <ConnectionFields
              connections={connections}
              connectionId={editing.id}
              independentScope={independentScope}
              presets={presets}
            />
          ) : (
            <ModelFields
              connections={connections}
              users={users}
              presets={presets}
              saved={models.find((model) => model.id === editing?.id)}
            />
          )}
        </Form>
      </Modal>
    </div>
  );
}
