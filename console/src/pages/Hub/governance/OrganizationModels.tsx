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
  type ManagedModel,
  type UsageReport,
} from "../../../api/modules/hubGovernance";
import { ConnectionFields, ModelFields } from "./ModelForms";
import { editable, useGovernanceText } from "./shared";
import styles from "./governance.module.less";

export default function OrganizationModels({
  initialModel,
}: {
  initialModel?: string;
}) {
  const text = useGovernanceText();
  const { message } = App.useApp();
  const [policy, setPolicy] = useState<ModelPolicy>();
  const [connections, setConnections] = useState<ModelConnection[]>([]);
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
      const [p, c, m, u, s] = await Promise.all([
        request<ModelPolicy>("admin/model-policy"),
        request<ModelConnection[]>("admin/model-connections"),
        request<ManagedModel[]>("admin/models"),
        request<UsageReport>("admin/usage"),
        request<typeof status>("admin/model-status"),
      ]);
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
    }
    if (value) {
      const data = editable(value);
      if ("has_key" in data) delete data.has_key;
      form.setFieldsValue(data);
    } else
      form.setFieldsValue(
        type === "connection"
          ? { enabled: true, requests_per_minute: 60, concurrency: 4 }
          : {
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
            {text("团队管理", "WORKSPACE")}
          </span>
          <h2>{text("模型", "Models")}</h2>
          <p>
            {text(
              "为成员提供开箱即用的模型，统一管理连接与访问权限。",
              "Ready-to-use models for your members, with centrally managed connections and access.",
            )}
          </p>
        </div>
        <div className={styles.actions}>
          <Button
            aria-label={text("刷新", "Refresh")}
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
              ? text("添加供应商", "Add provider")
              : text("添加模型", "Add model")}
          </Button>
        </div>
      </div>
      {error && (
        <div role="alert" className={styles.notice}>
          {error}
          <Button onClick={load}>{text("重试", "Retry")}</Button>
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
              <strong>{text("组织模型", "Organization models")}</strong>
              <p>
                {text(
                  "成员默认使用组织提供的模型，无需配置密钥。",
                  "Members use organization models by default, without configuring credentials.",
                )}
              </p>
            </div>
            <Tag
              bordered={false}
              color={models.some((m) => m.enabled) ? "success" : "default"}
            >
              {models.some((m) => m.enabled)
                ? text("可用", "Available")
                : text("待配置", "Setup")}
            </Tag>
          </div>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            items={[
              {
                key: "models",
                label: text("可用模型", "Models"),
                children: (
                  <div className={styles.panel}>
                    {!models.length ? (
                      <div className={styles.onboarding}>
                        <Boxes size={32} />
                        <h3>
                          {text(
                            "让成员直接开始使用模型",
                            "Give your members a model to start with",
                          )}
                        </h3>
                        <p>
                          {text(
                            "配置一次，全体成员即可使用，无需分发 API Key。",
                            "Configure once, without distributing API keys to your members.",
                          )}
                        </p>
                        <div className={styles.steps}>
                          {[
                            text("添加供应商", "Add provider"),
                            text("添加并测试模型", "Add and test model"),
                            text("设置默认模型", "Set default model"),
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
                            ? text("添加第一个模型", "Add your first model")
                            : text("连接供应商", "Connect a provider")}
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
                                  ? text("可用", "Available")
                                  : text("已停用", "Disabled")}
                              </Tag>
                            </div>
                            <h3>
                              {m.name}{" "}
                              {policy.default_model_id === m.id && (
                                <Tag bordered={false} color="orange">
                                  {text("默认", "Default")}
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
                              <span>{text("访问范围", "Access")}</span>
                              <strong>
                                {m.all_members
                                  ? text("全体成员", "All members")
                                  : `${m.user_ids.length} ${text(
                                      "位成员",
                                      "members",
                                    )}`}
                              </strong>
                            </div>
                            <div className={styles.actions}>
                              <Button onClick={() => open("model", m)}>
                                {text("配置", "Configure")}
                              </Button>
                              <Button
                                onClick={async () => {
                                  try {
                                    await request(
                                      `admin/models/${m.id}/test`,
                                      "POST",
                                    );
                                    message.success(
                                      text("连接正常", "Connection succeeded"),
                                    );
                                  } catch (e) {
                                    message.error((e as Error).message);
                                  }
                                }}
                              >
                                {text("测试连接", "Test connection")}
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
                            <h3>{text("成员默认体验", "Member defaults")}</h3>
                            <p>
                              {text(
                                "新会话默认使用此模型，成员可切换到其他已授权模型。",
                                "New conversations start with this model. Members can switch to other authorized models.",
                              )}
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
                                text("模型设置已保存", "Model settings saved"),
                              );
                            } catch (e) {
                              message.error((e as Error).message);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          <Form.Item
                            name="default_model_id"
                            label={text("默认模型", "Default model")}
                          >
                            <Select
                              placeholder={text(
                                "选择全体成员可用的模型",
                                "Choose a model available to all members",
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
                            {text("保存模型设置", "Save model settings")}
                          </Button>
                        </Form>
                      </article>
                    )}
                  </div>
                ),
              },
              {
                key: "connections",
                label: text("供应商连接", "Providers"),
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
                                  ? text("已启用", "Enabled")
                                  : text("已停用", "Disabled")}
                              </Tag>
                            </div>
                            <h3>{c.name}</h3>
                            <p>{c.base_url}</p>
                            <div className={styles.detailRow}>
                              <span>API Key</span>
                              <strong>
                                {c.has_key
                                  ? text("已安全保存", "Securely stored")
                                  : text("未配置", "Not configured")}
                              </strong>
                            </div>
                            <Button
                              icon={<Edit3 size={14} />}
                              onClick={() => open("connection", c)}
                            >
                              {text("管理连接", "Manage connection")}
                            </Button>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <div className={styles.empty}>
                        <Plug size={28} />
                        <strong>
                          {text("还没有供应商连接", "No providers yet")}
                        </strong>
                        <p>
                          {text(
                            "添加兼容 OpenAI 的模型服务，密钥仅保存在 Hub。",
                            "Connect an OpenAI-compatible service. Credentials stay in Hub.",
                          )}
                        </p>
                      </div>
                    )}
                    <details className={styles.help}>
                      <summary>
                        {text("部署与生效状态", "Deployment and activation")}
                      </summary>
                      <p>
                        {text(
                          "模型与权限在下次访问时自动更新，运行环境连接由 Hub 管理。",
                          "Models and permissions refresh on the next access. Hub manages runtime connectivity.",
                        )}
                      </p>
                      {status.map((s) => (
                        <div key={s.runtime_id} className={styles.detailRow}>
                          <span>{s.runtime_id}</span>
                          <span>
                            {s.observed_revision === null
                              ? text("尚未连接", "Not connected")
                              : s.observed_revision === policy.revision
                              ? text("已同步", "Synced")
                              : text("等待同步", "Pending")}
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
            ? text("供应商连接", "Provider connection")
            : text("模型配置", "Model configuration")
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
          onFinish={async (values) => {
            if (!editing) return;
            setBusy(true);
            try {
              const body = { ...values, revision: editing.revision };
              if (editing.type === "connection" && !body.api_key)
                delete body.api_key;
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
              message.error((e as Error).message);
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
            />
          ) : (
            <ModelFields connections={connections} users={users} />
          )}
        </Form>
      </Modal>
    </div>
  );
}
