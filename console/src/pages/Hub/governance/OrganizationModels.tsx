import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useState, useRef } from "react";
import { App, Button, Form, Modal, Select, Tabs, Skeleton, Tag } from "antd";
import {
  Edit3,
  Plus,
  RefreshCw,
  Boxes,
  Plug,
  ArrowRight,
  Check,
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
import { ConnectionFields, ModelFields } from "./ModelForms";
import { editable } from "./shared";
import { governanceErrorMessage } from "./errors";
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
  const [status, setStatus] = useState<
    {
      runtime_id: string;
      observed_revision: number | null;
      used_revision: number | null;
    }[]
  >([]);
  const [editing, setEditing] = useState<{
    type: "connection" | "model";
    id?: string;
    revision?: number;
  }>();
  const [independentScope, setIndependentScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("models");
  const [error, setError] = useState("");
  const [form] = Form.useForm();
  const [policyForm] = Form.useForm();
  const load = useCallback(async () => {
    try {
      const [p, c, m, u, s, presets] = await Promise.all([
        request<ModelPolicy>("admin/model-policy"),
        request<ModelConnection[]>("admin/model-connections"),
        request<ManagedModel[]>("admin/models"),
        request<UsageReport>("admin/usage"),
        request<typeof status>("admin/model-status"),
        request<ModelProviderPreset[]>("admin/model-provider-presets"),
      ]);
      setPresets(presets);
      setPolicy(p);
      setError("");
      setConnections(c);
      setModels(m);
      setUsers(u.members);
      setStatus(s);
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
          ? { enabled: true, requests_per_minute: 60, concurrency: 4 }
          : {
              connection_id: connectionId ?? connections[0]?.id,
              description: "",
              enabled: true,
              all_members: true,
              user_ids: [],
              output_token_limit: 4096,
              output_limit_field: "max_tokens",
              budget_verified: false,
              supports_image: false,
              requests_per_minute: 60,
              concurrency: 4,
            },
      );
    setEditing({ type, id: value?.id, revision: value?.revision });
  };
  const openedInitial = useRef<string>();
  useEffect(() => {
    if (!initialModel || openedInitial.current === initialModel) return;
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
          <p>{t("hub.governance.models.subtitle")}</p>
        </div>
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
          <div className={styles.serviceStrip}>
            <span className={styles.serviceIcon}>
              <Boxes size={20} />
            </span>
            <div>
              <strong>{t("hub.governance.models.organizationTitle")}</strong>
              <p>{t("hub.governance.models.organizationHint")}</p>
            </div>
            <Tag
              bordered={false}
              color={models.some((m) => m.enabled) ? "success" : "default"}
            >
              {models.some((m) => m.enabled)
                ? t("hub.runtimes.available")
                : t("hub.governance.models.setup")}
            </Tag>
          </div>
          <Tabs
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
                        <p>{t("hub.governance.models.emptyDescription")}</p>
                        <div className={styles.steps}>
                          {[
                            t("hub.governance.models.addProvider"),
                            t("hub.governance.models.addAndTest"),
                            t("hub.governance.models.setDefault"),
                          ].map((label, i) => (
                            <span key={label}>
                              <b>
                                {i === 0 && connections.length ? (
                                  <Check size={13} />
                                ) : (
                                  i + 1
                                )}
                              </b>
                              {label}
                            </span>
                          ))}
                        </div>
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
                              <span className={styles.serviceIcon}>
                                <Boxes size={19} />
                              </span>
                              <Tag
                                bordered={false}
                                color={m.enabled ? "success" : "default"}
                              >
                                {m.enabled
                                  ? t("hub.runtimes.available")
                                  : t("common.disabled")}
                              </Tag>
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
                                connections.find(
                                  (c) => c.id === m.connection_id,
                                )?.name}
                            </p>
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
                            <p>
                              {t("hub.governance.models.memberDefaultsHint")}
                            </p>
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
                              options={models
                                .filter((m) => m.enabled && m.all_members)
                                .map((m) => ({ value: m.id, label: m.name }))}
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
                              <span className={styles.serviceIcon}>
                                <Plug size={19} />
                              </span>
                              <Tag
                                bordered={false}
                                color={c.enabled ? "success" : "default"}
                              >
                                {c.enabled
                                  ? t("common.enabled")
                                  : t("common.disabled")}
                              </Tag>
                            </div>
                            <h3>{c.name}</h3>
                            <p>{c.base_url}</p>
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
                        <p>{t("hub.governance.models.noProvidersHint")}</p>
                      </div>
                    )}
                    <details className={styles.help}>
                      <summary>{t("hub.governance.models.deployment")}</summary>
                      <p>{t("hub.governance.models.deploymentHint")}</p>
                      {status.map((s) => (
                        <div key={s.runtime_id} className={styles.detailRow}>
                          <span>{s.runtime_id}</span>
                          <span>
                            {s.observed_revision === null
                              ? t("hub.governance.models.disconnected")
                              : s.observed_revision === policy.revision
                              ? t("hub.governance.models.synced")
                              : t("hub.governance.models.pending")}
                          </span>
                        </div>
                      ))}
                    </details>
                  </div>
                ),
              },
            ]}
          />
        </>
      )}
      <Modal
        open={!!editing}
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
          layout="vertical"
          className={styles.form}
          onValuesChange={(changed) => {
            if (editing?.type !== "model") return;
            if ("connection_id" in changed) {
              form.setFieldsValue({
                upstream_model: undefined,
                name: undefined,
                input_token_limit: undefined,
                supports_image: false,
                budget_verified: false,
              });
            } else if ("upstream_model" in changed) {
              form.setFieldValue("budget_verified", false);
            }
          }}
          onFinish={async (values) => {
            if (!editing) return;
            setBusy(true);
            try {
              const body = { ...values, revision: editing.revision };
              if (editing.type === "connection") {
                if (!body.api_key) delete body.api_key;
                body.provider_id = body.provider_id || null;
              } else {
                body.name = body.name?.trim() || body.upstream_model?.trim();
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
            />
          )}
        </Form>
      </Modal>
    </div>
  );
}
