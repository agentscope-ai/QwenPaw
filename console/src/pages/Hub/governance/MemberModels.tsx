import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Select } from "antd";
import { RefreshCw } from "lucide-react";
import {
  governanceRequest as request,
  type BudgetUsage,
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
  const [catalog, setCatalog] = useState<{
    enabled: boolean;
    default_model_id: string;
    models: { id: string; name: string }[];
  }>();
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
      if (!compact && models.enabled) {
        const active = await providerApi.getActiveModels();
        setSelected(active.active_llm?.model ?? models.default_model_id);
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
  if (!catalog?.enabled)
    return compact ? null : (
      <Alert
        type="info"
        message={
          error ||
          text(
            "组织尚未提供模型，请联系管理员。",
            "No organization models available. Contact your administrator.",
          )
        }
      />
    );
  const member = usage?.member;
  const blocked = member?.remaining === 0 || usage?.organization_blocked;
  const balance = `${text("本月剩余 Token", "Monthly tokens remaining")}: ${
    member?.remaining?.toLocaleString() ?? text("不限", "Unlimited")
  }`;
  return (
    <div className={compact ? styles.summary : styles.panel}>
      {!compact && <h2>{text("组织提供的模型", "Organization models")}</h2>}
      <span>{balance}</span>
      {member &&
        member.token_limit !== null &&
        member.token_limit > 0 &&
        (member.remaining ?? 0) <= member.token_limit * 0.2 && (
          <span>{text("额度已使用超过 80%", "Over 80% of budget used")}</span>
        )}
      {blocked && (
        <span>
          {text(
            "额度已用完，请联系管理员",
            "Budget exhausted. Contact your administrator",
          )}
        </span>
      )}
      {error && <span role="alert">{error}</span>}
      {!compact && (
        <>
          <p>
            {text(
              "连接与密钥由管理员管理。每次调用还需要足够的在途预留额度。",
              "Connections and keys are managed by your administrator. Each call also requires sufficient reservation capacity.",
            )}
          </p>
          <Select
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
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          />
        </>
      )}
      <Button
        size="small"
        aria-label={text("刷新额度", "Refresh budget")}
        icon={<RefreshCw size={14} />}
        onClick={load}
      />
    </div>
  );
}
