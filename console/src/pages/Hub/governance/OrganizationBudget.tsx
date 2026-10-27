import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { App, Button, Select, Skeleton } from "antd";
import {
  governanceRequest as request,
  type ModelPolicy,
  type UsageReport,
} from "../../../api/modules/hubGovernance";
import BudgetEditor from "./BudgetEditor";
import { budgetMode, budgetLimit, type BudgetMode } from "./budgetUtils";
import { governanceErrorMessage } from "./errors";
import styles from "./governance.module.less";
import layout from "./OrganizationBudget.module.less";

export default function OrganizationBudget() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [policy, setPolicy] = useState<ModelPolicy>();
  const [mode, setMode] = useState<BudgetMode>("unlimited");
  const [amount, setAmount] = useState<number | null>(null);
  const [memberMode, setMemberMode] = useState<BudgetMode>("unlimited");
  const [memberAmount, setMemberAmount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    try {
      const [p, r] = await Promise.all([
        request<ModelPolicy>("admin/model-policy"),
        request<UsageReport>("admin/usage"),
      ]);
      setPolicy(p);
      setMode(budgetMode(r.organization.token_limit));
      setAmount(r.organization.token_limit);
      setMemberMode(budgetMode(p.member_token_limit));
      setMemberAmount(p.member_token_limit);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  if (error)
    return (
      <div role="alert" className={styles.card}>
        {governanceErrorMessage(error, t)}
        <Button onClick={load}>{t("common.retry")}</Button>
      </div>
    );
  if (!policy) return <Skeleton active />;
  const save = async (defaults: boolean) => {
    if (
      (!defaults && mode === "limited" && !amount) ||
      (defaults && memberMode === "limited" && !memberAmount)
    ) {
      message.error(t("hub.governance.budget.positiveLimit"));
      return;
    }
    setBusy(true);
    try {
      if (defaults) {
        const next = await request<ModelPolicy>("admin/model-policy", "PUT", {
          ...policy,
          member_token_limit: budgetLimit(memberMode, memberAmount),
        });
        setPolicy(next);
      } else {
        await request("admin/budgets/organization", "PUT", {
          inherit: false,
          token_limit: budgetLimit(mode, amount),
        });
      }
      message.success(t("hub.governance.budget.saved"));
    } catch (e) {
      message.error(governanceErrorMessage(e, t));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={layout.settings}>
      <article className={layout.section}>
        <h3>{t("hub.governance.budget.organizationMonthly")}</h3>
        <div className={layout.controls}>
          <BudgetEditor
            mode={mode}
            amount={amount}
            onMode={setMode}
            onAmount={setAmount}
          />
          <div className={layout.actions}>
            <Button type="primary" loading={busy} onClick={() => save(false)}>
              {t("common.save")}
            </Button>
          </div>
        </div>
      </article>
      <article className={layout.section}>
        <h3>{t("hub.governance.budget.defaultMember")}</h3>
        <div className={layout.controls}>
          <BudgetEditor
            mode={memberMode}
            amount={memberAmount}
            onMode={setMemberMode}
            onAmount={setMemberAmount}
          />
          <div className={styles.field}>
            <label>{t("hub.governance.budget.timezone")}</label>
            <Select
              aria-label={t("hub.governance.budget.timezone")}
              value={policy.timezone}
              onChange={(timezone) => setPolicy({ ...policy, timezone })}
              options={[
                ...new Set([
                  policy.timezone,
                  "Asia/Shanghai",
                  "UTC",
                  "America/New_York",
                  "Europe/London",
                  "Asia/Tokyo",
                ]),
              ].map((value) => ({ value, label: value }))}
            />
          </div>
          <div className={layout.actions}>
            <Button type="primary" loading={busy} onClick={() => save(true)}>
              {t("common.save")}
            </Button>
          </div>
        </div>
      </article>
    </div>
  );
}
