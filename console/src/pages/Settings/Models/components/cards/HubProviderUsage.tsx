import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useState } from "react";
import { Button, Progress } from "antd";
import { RefreshCw } from "lucide-react";
import {
  governanceRequest as request,
  type BudgetUsage,
} from "../../../../../api/modules/hubGovernance";
import { governanceErrorMessage } from "../../../../Hub/governance/errors";
import styles from "./HubProviderUsage.module.less";

export default function HubProviderUsage() {
  const { t, i18n } = useTranslation();
  const [usage, setUsage] = useState<{
    member: BudgetUsage;
    organization_blocked: boolean;
  }>();
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setUsage(await request<NonNullable<typeof usage>>("me/usage"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [load]);
  const member = usage?.member;
  const blocked = member?.remaining === 0 || usage?.organization_blocked;
  const percent = member?.token_limit
    ? Math.min(
        100,
        ((member.charged + member.reserved) / member.token_limit) * 100,
      )
    : member?.token_limit === 0
    ? 100
    : 0;
  const number = (value: number) => value.toLocaleString(i18n.language);
  return (
    <div className={styles.usage}>
      <div className={styles.row}>
        <span>{t("hub.governance.dashboard.monthlyTokens")}</span>
        <Button
          type="text"
          size="small"
          aria-label={t("hub.governance.member.refreshBudget")}
          icon={<RefreshCw size={13} />}
          onClick={load}
        />
      </div>
      {member ? (
        <>
          <div className={styles.amount}>
            <strong>{number(member.charged)}</strong>
            <span>
              /{" "}
              {member.token_limit === null
                ? t("hub.governance.budget.unlimited")
                : number(member.token_limit)}
            </span>
          </div>
          {member.token_limit !== null && (
            <Progress
              percent={percent}
              showInfo={false}
              status={blocked ? "exception" : undefined}
              strokeColor={
                blocked ? "var(--app-error-text)" : "var(--app-accent)"
              }
              size="small"
              aria-label={t("hub.governance.users.usageBudget")}
            />
          )}
          {member.remaining !== null && (
            <div className={styles.row}>
              <span>{t("hub.governance.dashboard.remaining")}</span>
              <span>{number(member.remaining)}</span>
            </div>
          )}
          {member.reserved > 0 && (
            <div className={styles.row}>
              <span>{t("hub.governance.dashboard.reserved")}</span>
              <span>{number(member.reserved)}</span>
            </div>
          )}
        </>
      ) : (
        !error && <span>{t("hub.governance.member.loadingBudget")}</span>
      )}
      {blocked && (
        <span className={styles.warning}>
          {t("hub.governance.member.budgetUnavailable")}
        </span>
      )}
      {error && (
        <span role="alert" className={styles.warning}>
          {governanceErrorMessage(error, t)}
        </span>
      )}
    </div>
  );
}
