import { useCallback, useEffect, useState } from "react";
import {
  App,
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Switch,
  Select,
} from "antd";
import { Download, Plus, X } from "lucide-react";
import {
  governanceRequest as request,
  type InviteBatch,
} from "../../../api/modules/hubGovernance";
import { useGovernanceText } from "./shared";
import styles from "./governance.module.less";

export default function Invitations() {
  const text = useGovernanceText();
  const { message, modal } = App.useApp();
  const [models, setModels] = useState<{ id: string; name: string }[]>([]);
  const [batches, setBatches] = useState<InviteBatch[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [codes, setCodes] = useState<string[]>([]);
  const [form] = Form.useForm();
  const [requestId, setRequestId] = useState("");
  const load = useCallback(async () => {
    try {
      const [items, directory] = await Promise.all([
        request<InviteBatch[]>("admin/invite-batches"),
        request<{ id: string; name: string }[]>("admin/models"),
      ]);
      setBatches(items);
      setModels(directory);
    } catch (e) {
      message.error((e as Error).message);
    }
  }, [message]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <h2>{text("邀请码", "Invitations")}</h2>
          <p>
            {text(
              "每码开通一位成员，自动继承组织模型。请先在组织模型中开启邀请注册。",
              "Each code creates one member with organization models. Enable invitation registration under Organization models first.",
            )}
          </p>
        </div>
        <Button
          icon={<Plus size={16} />}
          type="primary"
          onClick={() => {
            setRequestId(crypto.randomUUID());
            setOpen(true);
          }}
        >
          {text("生成邀请码", "Generate invitations")}
        </Button>
      </div>
      <div className={styles.grid}>
        {batches.map((batch) => (
          <div className={styles.card} key={batch.id}>
            <h3>{batch.note || batch.id.slice(0, 8)}</h3>
            <div className={styles.metric}>
              {batch.redeemed} / {batch.total}
            </div>
            <p>
              {text("已兑换 / 总数", "Redeemed / total")} ·{" "}
              {text("已撤销", "Revoked")} {batch.revoked}
            </p>
            <p>
              {text("到期", "Expires")}{" "}
              {new Date(batch.expires_at).toLocaleString()}
            </p>
            <Button
              icon={<X size={14} />}
              disabled={batch.redeemed + batch.revoked >= batch.total}
              onClick={() =>
                modal.confirm({
                  title: text(
                    "撤销未兑换的邀请码？",
                    "Revoke unused invitations?",
                  ),
                  onOk: async () => {
                    await request(
                      `admin/invite-batches/${batch.id}/revoke`,
                      "POST",
                    );
                    await load();
                  },
                })
              }
            >
              {text("撤销剩余", "Revoke unused")}
            </Button>
          </div>
        ))}
      </div>
      <Modal
        title={text("批量开通", "Invite members")}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            count: 10,
            valid_days: 7,
            inherit_budget: true,
            model_ids: [],
            token_limit: null,
            note: "",
          }}
          onFinish={async (values) => {
            setBusy(true);
            try {
              const result = await request<{ codes: { code: string }[] }>(
                "admin/invite-batches",
                "POST",
                { ...values, request_id: requestId },
              );
              setCodes(result.codes.map((c) => c.code));
              setOpen(false);
              await load();
            } catch (e) {
              message.error((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item
            name="model_ids"
            label={text(
              "额外模型授权（自动继承全员模型）",
              "Additional grants (all-member models are inherited)",
            )}
          >
            <Select
              mode="multiple"
              options={models.map((model) => ({
                value: model.id,
                label: model.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="note" label={text("批次备注", "Batch note")}>
            <Input maxLength={256} />
          </Form.Item>
          <Form.Item
            name="count"
            label={text("数量", "Count")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={100} precision={0} />
          </Form.Item>
          <Form.Item
            name="valid_days"
            label={text("有效天数", "Valid days")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={90} precision={0} />
          </Form.Item>
          <Form.Item
            name="inherit_budget"
            label={text("继承成员默认额度", "Inherit member budget")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="token_limit"
            label={text(
              "个人月 Token 额度（空为不限）",
              "Monthly tokens (empty means unlimited)",
            )}
          >
            <InputNumber min={0} precision={0} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={text("邀请码仅显示一次", "Codes are shown once")}
        open={codes.length > 0}
        onCancel={() => setCodes([])}
        onOk={() => setCodes([])}
        width={720}
      >
        <Alert
          type="info"
          showIcon
          message={text(
            "关闭前请保存。后续无法回读原码。",
            "Save before closing. Codes cannot be retrieved later.",
          )}
        />
        <pre className={styles.codes}>{codes.join("\n")}</pre>
        <Button
          icon={<Download size={14} />}
          onClick={() => {
            const url = URL.createObjectURL(
              new Blob([codes.join("\n")], { type: "text/plain" }),
            );
            const a = document.createElement("a");
            a.href = url;
            a.download = "hub-invitations.txt";
            a.click();
            URL.revokeObjectURL(url);
          }}
        >
          {text("下载邀请码", "Download codes")}
        </Button>
      </Modal>
    </div>
  );
}
