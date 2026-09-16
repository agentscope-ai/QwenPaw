import { createClientMessageId } from "../../../utils/clientMessageId";
import { useCallback, useEffect, useState } from "react";
import {
  App,
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Tag,
  Select,
} from "antd";
import { Download, Plus, X, Ticket, Info } from "lucide-react";
import {
  governanceRequest as request,
  type InviteBatch,
} from "../../../api/modules/hubGovernance";
import BudgetEditor from "./BudgetEditor";
import { budgetLimit, type BudgetMode } from "./budgetUtils";
import { hubApi } from "../../../api/modules/hub";
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
  const [budgetMode, setBudgetMode] = useState<BudgetMode>("inherit");
  const [amount, setAmount] = useState<number | null>(null);
  const [registrationMode, setRegistrationMode] = useState<string>();
  const [requestId, setRequestId] = useState("");
  const load = useCallback(async () => {
    try {
      const [items, directory, settings] = await Promise.all([
        request<InviteBatch[]>("admin/invite-batches"),
        request<{ id: string; name: string }[]>("admin/models"),
        hubApi.getSettings(),
      ]);
      setRegistrationMode(settings.config.control_plane.registration.mode);
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
          <h3>{text("邀请成员加入", "Invite members")}</h3>
          <p>
            {text(
              "每个邀请码可创建一个成员账号，自动继承组织默认权限和额度。",
              "Each code creates one member with the organization’s default access and budget.",
            )}
          </p>
        </div>
        <Button
          icon={<Plus size={16} />}
          type="primary"
          onClick={() => {
            setRequestId(createClientMessageId());
            setOpen(true);
          }}
        >
          {text("生成邀请码", "Generate invitations")}
        </Button>
      </div>
      {registrationMode && registrationMode !== "invite" && (
        <div className={styles.notice}>
          <Info size={16} />
          <span>
            {text(
              "当前未启用邀请注册。可先创建邀请码，前往系统设置 → 访问与注册切换模式后即可使用。",
              "Invitation registration is not active. Prepare codes now, then enable invitation mode in Settings → Access & registration.",
            )}
          </span>
        </div>
      )}
      {!batches.length && (
        <div className={styles.tablePanel}>
          <div className={styles.empty}>
            <Ticket size={28} />
            <strong>{text("邀请下一位成员", "Invite your next member")}</strong>
            <p>
              {text(
                "批量创建邀请码，统一设置有效期，再将邀请码交给成员。",
                "Create a batch, set an expiry date, and share the codes with your members.",
              )}
            </p>
          </div>
        </div>
      )}
      <div className={styles.grid}>
        {batches.map((batch) => (
          <div className={styles.card} key={batch.id}>
            <div className={styles.heading}>
              <h3>{batch.note || text("成员邀请", "Member invitation")}</h3>
              <Tag bordered={false}>
                {new Date(batch.expires_at).getTime() < Date.now()
                  ? text("已过期", "Expired")
                  : batch.redeemed + batch.revoked >= batch.total
                  ? text("已结束", "Completed")
                  : text("有效", "Active")}
              </Tag>
            </div>
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
              disabled={
                batch.redeemed + batch.revoked >= batch.total ||
                new Date(batch.expires_at).getTime() < Date.now()
              }
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
        closeIcon={<X size={18} />}
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
            if (budgetMode === "limited" && !amount) {
              message.error(
                text("请输入大于 0 的额度", "Enter a limit greater than zero"),
              );
              return;
            }
            setBusy(true);
            try {
              const result = await request<{ codes: { code: string }[] }>(
                "admin/invite-batches",
                "POST",
                {
                  ...values,
                  request_id: requestId,
                  inherit_budget: budgetMode === "inherit",
                  token_limit: budgetLimit(budgetMode, amount),
                },
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
          <details className={styles.help}>
            <summary>
              {text(
                "自定义权限与额度（可选）",
                "Customize access and budget (optional)",
              )}
            </summary>
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
            <BudgetEditor
              mode={budgetMode}
              amount={amount}
              onMode={setBudgetMode}
              onAmount={setAmount}
              allowInherit
            />
          </details>
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
          icon={<Info size={16} />}
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
