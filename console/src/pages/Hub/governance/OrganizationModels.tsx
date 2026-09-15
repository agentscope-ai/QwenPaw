import { useCallback, useEffect, useState } from "react";
import {
  App,
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Switch,
  Tag,
} from "antd";
import { Edit3, Plus, RefreshCw } from "lucide-react";
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

export default function OrganizationModels() {
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
  const [busy, setBusy] = useState(false);
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
      setConnections(c);
      setModels(m);
      setUsers(u.members);
      setStatus(s);
      policyForm.setFieldsValue(p);
    } catch (e) {
      message.error((e as Error).message);
    }
  }, [message, policyForm]);
  useEffect(() => {
    void load();
  }, [load]);
  const open = (
    type: "connection" | "model",
    value?: ModelConnection | ManagedModel,
  ) => {
    form.resetFields();
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
  return (
    <div className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <h2>{text("组织模型", "Organization models")}</h2>
          <p>
            {text(
              "凭据留在 Hub，成员只使用授权模型。",
              "Credentials stay in Hub. Members use authorized models.",
            )}
          </p>
        </div>
        <Button icon={<RefreshCw size={16} />} onClick={load}>
          {text("刷新", "Refresh")}
        </Button>
      </div>
      <Alert
        type="info"
        showIcon
        message={text(
          "首次启用后，请重启现有 Runtime。容器需配置可达的 Hub 模型入口。",
          "Restart existing runtimes after enabling. Containers need a reachable Hub model endpoint.",
        )}
      />
      <div className={styles.heading}>
        <h3>{text("上游连接", "Connections")}</h3>
        <Button icon={<Plus size={14} />} onClick={() => open("connection")}>
          {text("添加连接", "Add connection")}
        </Button>
      </div>
      <div className={styles.grid}>
        {connections.map((c) => (
          <div key={c.id} className={styles.card}>
            <h3>{c.name}</h3>
            <p>{c.base_url}</p>
            <p>
              {text("密钥已保存，仅可替换", "Key stored; replacement only")} ·{" "}
              {c.enabled ? text("启用", "Enabled") : text("停用", "Disabled")}
            </p>
            <Button
              icon={<Edit3 size={14} />}
              onClick={() => open("connection", c)}
            >
              {text("编辑 / 轮换 Key", "Edit / rotate key")}
            </Button>
          </div>
        ))}
      </div>
      <div className={styles.heading}>
        <h3>{text("发布目录", "Published models")}</h3>
        <Button
          disabled={!connections.length}
          icon={<Plus size={14} />}
          onClick={() => open("model")}
        >
          {text("添加模型", "Add model")}
        </Button>
      </div>
      <div className={styles.grid}>
        {models.map((m) => (
          <div key={m.id} className={styles.card}>
            <h3>{m.name}</h3>
            <p>{m.description}</p>
            <div>
              <Tag>
                {m.all_members
                  ? text("全体成员", "All members")
                  : `${m.user_ids.length} ${text("位成员", "members")}`}
              </Tag>
              <Tag>
                {m.enabled
                  ? text("已发布", "Published")
                  : text("已下架", "Disabled")}
              </Tag>
            </div>
            <div className={styles.actions}>
              <Button onClick={() => open("model", m)}>
                {text("编辑", "Edit")}
              </Button>
              <Button
                onClick={async () => {
                  try {
                    await request(`admin/models/${m.id}/test`, "POST");
                    message.success(
                      text("连通性测试成功", "Connection test succeeded"),
                    );
                  } catch (e) {
                    message.error((e as Error).message);
                  }
                }}
              >
                {text("测试调用", "Test call")}
              </Button>
            </div>
          </div>
        ))}
      </div>
      <Form
        form={policyForm}
        className={styles.form}
        layout="vertical"
        onFinish={async (values) => {
          setBusy(true);
          try {
            const next = await request<ModelPolicy>(
              "admin/model-policy",
              "PUT",
              {
                ...values,
                revision: policy?.revision,
                default_model_id: values.default_model_id ?? null,
                member_token_limit: values.member_token_limit ?? null,
              },
            );
            setPolicy(next);
            policyForm.setFieldsValue(next);
            message.success(
              text(
                "已保存，等待 Runtime 确认",
                "Saved; awaiting runtime acknowledgement",
              ),
            );
          } catch (e) {
            message.error((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h3>{text("组织策略", "Organization policy")}</h3>
        <Form.Item
          name="enabled"
          label={text(
            "启用托管模型（关闭成员自配）",
            "Enable managed models (lock personal providers)",
          )}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="default_model_id"
          label={text("组织默认模型", "Default model")}
        >
          <Select
            allowClear
            options={models
              .filter((m) => m.enabled && m.all_members)
              .map((m) => ({ value: m.id, label: m.name }))}
          />
        </Form.Item>
        <Form.Item
          name="member_token_limit"
          label={text(
            "默认成员月 Token 额度（空为不限，0 为禁用）",
            "Default monthly member tokens (empty unlimited, 0 blocked)",
          )}
        >
          <InputNumber min={0} precision={0} />
        </Form.Item>
        <Form.Item
          name="timezone"
          label={text(
            "月度预算时区（使用后固定）",
            "Budget timezone (fixed after first use)",
          )}
          rules={[{ required: true }]}
        >
          <Input placeholder="UTC" />
        </Form.Item>
        <Form.Item
          name="invitation_enabled"
          label={text(
            "开启邀请注册（替代开放注册）",
            "Enable invitation registration (replaces open registration)",
          )}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
        <Button
          htmlType="submit"
          type="primary"
          loading={busy}
          disabled={!policy}
        >
          {text("保存策略", "Save policy")}
        </Button>
      </Form>
      <div className={styles.card}>
        <h3>
          {text("发布生效", "Publication status")} · {policy?.revision}
        </h3>
        {status.map((s) => (
          <p key={s.runtime_id}>
            {s.runtime_id} · {text("目录版本", "Catalog")}{" "}
            {s.observed_revision ?? text("待重启", "Restart required")} ·{" "}
            {text("成功调用版本", "Successful use")} {s.used_revision ?? "—"}
          </p>
        ))}
      </div>
      <Modal
        open={!!editing}
        title={text("模型配置", "Model configuration")}
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
            <ConnectionFields />
          ) : (
            <ModelFields connections={connections} users={users} />
          )}
        </Form>
      </Modal>
    </div>
  );
}
