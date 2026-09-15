import { useCallback, useEffect, useState } from "react";
import { Button, Select, Progress, Skeleton } from "antd";
import { RefreshCw, Boxes, Wallet } from "lucide-react";
import {
  governanceRequest as request,
  type BudgetUsage,
  type MemberModelCatalog,
} from "../../../api/modules/hubGovernance";
import { providerApi } from "../../../api/modules/provider";
import { useGovernanceText } from "./shared";
import styles from "./governance.module.less";

export default function MemberModels({
  compact = false,
}: {
  compact?: boolean;
}) {
  const text = useGovernanceText();
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
        {error}
        <Button onClick={load}>{text("重试", "Retry")}</Button>
      </div>
    ) : (
      <Skeleton active />
    );
  const member = usage?.member;
  const blocked = member?.remaining === 0 || usage?.organization_blocked;
  const balance = `${text(
    "Hub 本月剩余 Token",
    "Hub monthly tokens remaining",
  )}: ${member?.remaining?.toLocaleString() ?? text("不限", "Unlimited")}`;
  if (compact)
    return (
      <div className={styles.summary}>
        <Wallet size={13} />
        <span>{usage ? balance : text("额度加载中", "Loading budget")}</span>
        {blocked && (
          <span>
            {text(
              "额度不足，请联系管理员",
              "Budget unavailable. Contact your administrator",
            )}
          </span>
        )}
        {error && <span role="alert">{error}</span>}
        <Button
          type="text"
          size="small"
          aria-label={text("刷新额度", "Refresh budget")}
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
          <h3>{text("组织对话模型", "Organization conversation model")}</h3>
          <p>
            {text(
              "更改后将在新会话中使用。",
              "Changes apply to new conversations.",
            )}
          </p>
          {catalog.models.length === 0 ? (
            <div className={styles.empty}>
              <Boxes size={28} />
              <strong>{text("暂无可用模型", "No models available")}</strong>
              <p>
                {text(
                  "管理员发布模型并授权后即可使用。",
                  "Models appear here once your administrator publishes them and grants access.",
                )}
              </p>
            </div>
          ) : (
            <Select
              aria-label={text(
                "组织对话模型",
                "Organization conversation model",
              )}
              placeholder={text(
                "选择组织模型用于对话",
                "Choose an organization model for chat",
              )}
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
            {text(
              "模型访问权限由管理员管理，无需配置 API Key。",
              "Your administrator manages model access. No API key setup is required.",
            )}
          </small>
        </article>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{text("Hub 本月用量", "Hub monthly usage")}</h3>
            <Button
              type="text"
              aria-label={text("刷新额度", "Refresh budget")}
              icon={<RefreshCw size={14} />}
              onClick={load}
            />
          </div>
          {member ? (
            <>
              <strong className={styles.metric}>
                {member.charged.toLocaleString()} <small>Token</small>
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
          {text(
            "当前额度不足，请联系管理员调整。",
            "Your current budget is unavailable. Contact your administrator.",
          )}
        </div>
      )}
      {error && (
        <div className={styles.notice} role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
