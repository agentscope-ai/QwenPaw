import { useTranslation } from "react-i18next";
import { createClientMessageId } from "../../../utils/clientMessageId";
import { useCallback, useEffect, useState } from "react";
import {
  App,
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
import { governanceErrorMessage } from "./errors";
import styles from "./governance.module.less";

export default function Invitations() {
  const { t, i18n } = useTranslation();
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
      message.error(governanceErrorMessage(e, t));
    }
  }, [message, t]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className={styles.panel}>
      <div className={styles.heading}>
        <div>
          <h3>{t("hub.governance.invitations.title")}</h3>
        </div>
        <Button
          icon={<Plus size={16} />}
          type="primary"
          onClick={() => {
            setRequestId(createClientMessageId());
            setOpen(true);
          }}
        >
          {t("hub.governance.invitations.generate")}
        </Button>
      </div>
      {registrationMode && registrationMode !== "invite" && (
        <div className={styles.notice}>
          <Info size={16} />
          <span>
            {t("hub.governance.settings.registration")}:{" "}
            {t(`hub.governance.settings.${registrationMode}`)}
          </span>
        </div>
      )}
      {!batches.length && (
        <div className={styles.tablePanel}>
          <div className={styles.empty}>
            <Ticket size={28} />
            <strong>{t("hub.governance.invitations.emptyTitle")}</strong>
          </div>
        </div>
      )}
      <div className={styles.grid}>
        {batches.map((batch) => (
          <div className={styles.card} key={batch.id}>
            <div className={styles.heading}>
              <h3>
                {batch.note || t("hub.governance.invitations.batchTitle")}
              </h3>
              <Tag bordered={false}>
                {new Date(batch.expires_at).getTime() < Date.now()
                  ? t("hub.governance.invitations.expired")
                  : batch.redeemed + batch.revoked >= batch.total
                  ? t("hub.governance.invitations.completed")
                  : t("hub.governance.invitations.active")}
              </Tag>
            </div>
            <div className={styles.metric}>
              {batch.redeemed} / {batch.total}
            </div>
            <p>
              {t("hub.governance.invitations.redeemedTotal")} ·{" "}
              {t("hub.governance.invitations.revoked")} {batch.revoked}
            </p>
            <p>
              {t("hub.governance.invitations.expires")}{" "}
              {new Date(batch.expires_at).toLocaleString(i18n.language)}
            </p>
            <Button
              icon={<X size={14} />}
              disabled={
                batch.redeemed + batch.revoked >= batch.total ||
                new Date(batch.expires_at).getTime() < Date.now()
              }
              onClick={() =>
                modal.confirm({
                  title: t("hub.governance.invitations.revokeTitle"),
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
              {t("hub.governance.invitations.revoke")}
            </Button>
          </div>
        ))}
      </div>
      <Modal
        title={t("hub.governance.invitations.createTitle")}
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
              message.error(t("hub.governance.budget.positiveLimit"));
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
              message.error(governanceErrorMessage(e, t));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Form.Item name="note" label={t("hub.governance.invitations.note")}>
            <Input maxLength={256} />
          </Form.Item>
          <Form.Item
            name="count"
            label={t("hub.governance.invitations.count")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={100} precision={0} />
          </Form.Item>
          <Form.Item
            name="valid_days"
            label={t("hub.governance.invitations.validDays")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} max={90} precision={0} />
          </Form.Item>
          <details className={styles.help}>
            <summary>{t("hub.governance.invitations.customize")}</summary>
            <Form.Item
              name="model_ids"
              label={t("hub.governance.invitations.additionalGrants")}
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
        title={t("hub.governance.invitations.codesTitle")}
        open={codes.length > 0}
        onCancel={() => setCodes([])}
        onOk={() => setCodes([])}
        width={720}
      >
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
          {t("hub.governance.invitations.download")}
        </Button>
      </Modal>
    </div>
  );
}
