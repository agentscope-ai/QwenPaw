import { useEffect, useState } from "react";
import { App, Button, Select, Skeleton } from "antd";
import { Wallet } from "lucide-react";
import {
  governanceRequest as request,
  type ModelPolicy,
  type UsageReport,
} from "../../../api/modules/hubGovernance";
import BudgetEditor from "./BudgetEditor";
import { budgetMode, budgetLimit, type BudgetMode } from "./budgetUtils";
import { useGovernanceText } from "./shared";
import styles from "./governance.module.less";

export default function OrganizationBudget() {
  const text = useGovernanceText();
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
        {error}
        <Button onClick={load}>{text("重试", "Retry")}</Button>
      </div>
    );
  if (!policy) return <Skeleton active />;
  const save = async (defaults: boolean) => {
    if (
      (mode === "limited" && !amount) ||
      (memberMode === "limited" && !memberAmount)
    ) {
      message.error(
        text("请输入大于 0 的额度", "Enter a limit greater than zero"),
      );
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
      message.success(text("组织预算已保存", "Organization budget saved"));
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={styles.settingsColumns}>
      <article className={styles.card}>
        <div className={styles.heading}>
          <div>
            <h3>{text("组织月预算", "Organization monthly budget")}</h3>
            <p>
              {text(
                "所有成员共享的每月总额度。",
                "The monthly ceiling shared by all members.",
              )}
            </p>
          </div>
          <Wallet size={18} />
        </div>
        <BudgetEditor
          mode={mode}
          amount={amount}
          onMode={setMode}
          onAmount={setAmount}
        />
        <div className={styles.actions}>
          <Button type="primary" loading={busy} onClick={() => save(false)}>
            {text("保存预算", "Save budget")}
          </Button>
        </div>
      </article>
      <article className={styles.card}>
        <h3>{text("成员默认额度", "Default member budget")}</h3>
        <p>
          {text(
            "新成员和选择「继承组织默认」的成员使用此额度。单独调整额度请前往用户详情。",
            "Applies to new members and members using the organization default. Individual limits are managed in user details.",
          )}
        </p>
        <BudgetEditor
          mode={memberMode}
          amount={memberAmount}
          onMode={setMemberMode}
          onAmount={setMemberAmount}
        />
        <div className={styles.field}>
          <label>{text("结算时区", "Billing timezone")}</label>
          <Select
            aria-label={text("结算时区", "Billing timezone")}
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
          <small>
            {text(
              "每月 1 日重置。产生用量后，结算时区固定。",
              "Resets on the first of each month. The timezone is fixed after usage begins.",
            )}
          </small>
        </div>
        <Button type="primary" loading={busy} onClick={() => save(true)}>
          {text("保存默认设置", "Save defaults")}
        </Button>
      </article>
    </div>
  );
}
