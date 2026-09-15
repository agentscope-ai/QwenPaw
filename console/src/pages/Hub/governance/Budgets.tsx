import { useCallback, useEffect, useState } from "react";
import { App, Button, Form, InputNumber, Modal, Progress, Switch } from "antd";
import { RefreshCw } from "lucide-react";
import {
  governanceRequest as request,
  type BudgetUsage,
  type UsageReport,
} from "../../../api/modules/hubGovernance";
import { useGovernanceText } from "./shared";
import styles from "./governance.module.less";

export default function Budgets() {
  const text = useGovernanceText();
  const { message } = App.useApp();
  const [report, setReport] = useState<UsageReport>();
  const [edit, setEdit] = useState<BudgetUsage>();
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  const load = useCallback(
    () =>
      request<UsageReport>("admin/usage")
        .then(setReport)
        .catch((e) => message.error(e.message)),
    [message],
  );
  useEffect(() => {
    void load();
  }, [load]);
  const card = (usage: BudgetUsage, name: string) => (
    <div key={usage.subject} className={styles.card}>
      <h3>
        {name} · {usage.period}
      </h3>
      <div className={styles.metric}>
        {usage.charged.toLocaleString()} /{" "}
        {usage.token_limit?.toLocaleString() ?? text("不限", "Unlimited")}
      </div>
      {usage.token_limit !== null && (
        <Progress
          percent={
            usage.token_limit === 0
              ? 100
              : Math.min(
                  100,
                  Math.round(
                    (100 * (usage.charged + usage.reserved)) /
                      usage.token_limit,
                  ),
                )
          }
          status={usage.remaining === 0 ? "exception" : undefined}
        />
      )}
      <p>
        {text("已确认", "Confirmed")} {usage.actual.toLocaleString()} ·{" "}
        {text("保守扣额", "Conservative")} {usage.conservative.toLocaleString()}{" "}
        · {text("在途预留", "Reserved")} {usage.reserved.toLocaleString()}
      </p>
      <Button
        onClick={() => {
          setEdit(usage);
          form.setFieldsValue({
            token_limit: usage.token_limit,
            inherit: false,
          });
        }}
      >
        {text("调整额度", "Adjust budget")}
      </Button>
    </div>
  );
  return (
    <div className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <h2>{text("用量与预算", "Usage and budgets")}</h2>
          <p>
            {text(
              "仅统计 Hub 托管调用；用量缺失时保守扣额。额度不足以覆盖预留时将拒绝调用。",
              "Hub-managed calls only. Missing usage is charged conservatively. Calls require enough balance for reservation.",
            )}
          </p>
        </div>
        <Button icon={<RefreshCw size={16} />} onClick={load}>
          {text("刷新", "Refresh")}
        </Button>
      </div>
      {report && (
        <>
          {card(report.organization, text("组织总额度", "Organization budget"))}
          <div className={styles.grid}>
            {report.members.map((u) => card(u, u.username))}
          </div>
          <div className={styles.card}>
            <h3>{text("按模型统计", "Usage by model")}</h3>
            {report.models.map((m) => (
              <p key={m.model_id}>
                {m.model_id} · {m.charged.toLocaleString()} Token · {m.requests}{" "}
                {text("次请求", "requests")} · {m.failures}{" "}
                {text("次失败", "failures")}
              </p>
            ))}
          </div>
        </>
      )}
      <Modal
        open={!!edit}
        title={text("调整月额度", "Monthly budget")}
        onCancel={() => setEdit(undefined)}
        onOk={() => form.submit()}
        confirmLoading={busy}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={async (values) => {
            if (!edit) return;
            setBusy(true);
            try {
              await request(`admin/budgets/${edit.subject}`, "PUT", {
                ...values,
                token_limit: values.token_limit ?? null,
              });
              setEdit(undefined);
              await load();
            } catch (e) {
              message.error((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item
            name="token_limit"
            label={text(
              "Token（空为不限，0 禁止调用）",
              "Tokens (empty unlimited, 0 blocked)",
            )}
          >
            <InputNumber min={0} precision={0} />
          </Form.Item>
          {edit?.subject !== "organization" && (
            <Form.Item
              name="inherit"
              label={text("恢复继承组织默认值", "Inherit member default")}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
