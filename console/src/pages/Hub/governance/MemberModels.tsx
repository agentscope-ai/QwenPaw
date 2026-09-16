import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useState } from "react";
import { Button, Select, Progress, Skeleton } from "antd";
import { RefreshCw, Boxes, Wallet } from "lucide-react";
import {
  governanceRequest as request,
  type BudgetUsage,
  type MemberModelCatalog,
} from "../../../api/modules/hubGovernance";
import { providerApi } from "../../../api/modules/provider";
import { governanceErrorMessage } from "./errors";
import styles from "./governance.module.less";

export default function MemberModels({
  compact = false,
}: {
  compact?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const [catalog, setCatalog] = useState<MemberModelCatalog>();
  const [usage, setUsage] = useState<{
    member: BudgetUsage;
    organization_blocked: boolean;
  }>();
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string>();
  const load = useCallback(async () => {
    try {
      const [models, budget] = await Promise.all([
        request<NonNullable<typeof catalog>>("me/models"),
        request<NonNullable<typeof usage>>("me/usage"),
      ]);
      setCatalog(models);
      setUsage(budget);
      setError("");
      if (!compact && models.models.length) {
        const active = await providerApi.getActiveModels({ scope: "global" });
        setSelected(
          active.active_llm?.provider_id === "hub-managed"
            ? active.active_llm.model
            : undefined,
        );
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [compact]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, [load]);
  if (!catalog)
    return compact ? null : error ? (
      <div className={styles.card} role="alert">
        {governanceErrorMessage(error, t)}
        <Button onClick={load}>{t("common.retry")}</Button>
      </div>
    ) : (
      <Skeleton active />
    );
  const member = usage?.member;
  const blocked = member?.remaining === 0 || usage?.organization_blocked;
  const balance = t("hub.governance.member.balance", {
    remaining:
      member?.remaining?.toLocaleString(i18n.language) ??
      t("hub.governance.budget.unlimited"),
  });
  if (compact)
    return (
      <div className={styles.summary}>
        <Wallet size={13} />
        <span>
          {usage ? balance : t("hub.governance.member.loadingBudget")}
        </span>
        {blocked && <span>{t("hub.governance.member.budgetUnavailable")}</span>}
        {error && <span role="alert">{governanceErrorMessage(error, t)}</span>}
        <Button
          type="text"
          size="small"
          aria-label={t("hub.governance.member.refreshBudget")}
          icon={<RefreshCw size={13} />}
          onClick={load}
        />
      </div>
    );
  return (
    <div className={styles.panel}>
      <div className={styles.settingsColumns}>
        <article className={styles.card}>
          <span className={styles.serviceIcon}>
            <Boxes size={20} />
          </span>
          <h3>{t("hub.governance.member.conversationModel")}</h3>
          <p>{t("hub.governance.member.changesHint")}</p>
          {catalog.models.length === 0 ? (
            <div className={styles.empty}>
              <Boxes size={28} />
              <strong>{t("hub.governance.member.noModels")}</strong>
              <p>{t("hub.governance.member.noModelsHint")}</p>
            </div>
          ) : (
            <Select
              aria-label={t("hub.governance.member.conversationModel")}
              placeholder={t("hub.governance.member.chooseModel")}
              value={selected}
              options={catalog.models.map((m) => ({
                value: m.id,
                label: m.name,
              }))}
              onChange={async (model) => {
                try {
                  await providerApi.setActiveLlm({
                    provider_id: "hub-managed",
                    model,
                    scope: "global",
                  });
                  setSelected(model);
                  setError("");
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            />
          )}
          <small className={styles.muted}>
            {t("hub.governance.member.accessHint")}
          </small>
        </article>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{t("hub.governance.member.usage")}</h3>
            <Button
              type="text"
              aria-label={t("hub.governance.member.refreshBudget")}
              icon={<RefreshCw size={14} />}
              onClick={load}
            />
          </div>
          {member ? (
            <>
              <strong className={styles.metric}>
                {member.charged.toLocaleString(i18n.language)}{" "}
                <small>Token</small>
              </strong>
              <p>{balance}</p>
              {member.token_limit !== null && member.token_limit > 0 && (
                <Progress
                  status={blocked ? "exception" : "normal"}
                  percent={Math.min(
                    100,
                    Math.round(
                      ((member.charged + member.reserved) /
                        member.token_limit) *
                        100,
                    ),
                  )}
                  strokeColor="var(--app-accent)"
                  trailColor="var(--app-accent-soft)"
                />
              )}
              <small className={styles.muted}>{member.period}</small>
            </>
          ) : (
            <Skeleton active />
          )}
        </article>
      </div>
      {blocked && (
        <div className={styles.notice}>
          {t("hub.governance.member.contactAdmin")}
        </div>
      )}
      {error && (
        <div className={styles.notice} role="alert">
          {governanceErrorMessage(error, t)}
        </div>
      )}
    </div>
  );
}
