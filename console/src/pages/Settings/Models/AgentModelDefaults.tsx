import { useEffect, useState } from "react";
import { Select, Tooltip } from "antd";
import { ChevronDown, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "@/stores/agentStore";
import { agentsApi } from "@/api/modules/agents";
import { providerApi } from "@/api/modules/provider";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { ProviderInfo, ActiveModelsInfo } from "@/api/types";
import { AgentModelSettings } from "../../Chat/ModelSelector/AgentModelSettings";
import { buildEligibleProviders } from "../../Chat/ModelSelector/modelSelectorModels";
import styles from "./AgentModelDefaults.module.less";

export function AgentModelDefaults({
  providers,
  activeModels,
}: {
  providers: ProviderInfo[];
  activeModels: ActiveModelsInfo | null;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const agents = useAgentStore((s) => s.agents);
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const refresh = useAgentStore((s) => s.refreshAgents);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  useEffect(() => {
    void refresh().catch((error) => setLoadError(String(error)));
  }, [refresh]);
  const eligible = buildEligibleProviders(providers);
  const options = eligible.map((p) => ({
    label: p.name,
    options: p.models.map((m) => ({
      label: m.name || m.id,
      value: JSON.stringify({ provider_id: p.id, model: m.id }),
    })),
  }));
  async function save(agentId: string, value?: string) {
    setBusy(true);
    try {
      if (value)
        await providerApi.setActiveLlm({
          scope: "agent",
          agent_id: agentId,
          ...JSON.parse(value),
        });
      else await agentsApi.updateModelSettings(agentId, { active_model: null });
      await refresh();
    } catch (error) {
      message.error(String(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className={styles.section} aria-label={t("models.agentDefaults")}>
      <h3>{t("models.agentDefaults")}</h3>
      {loadError && <p role="alert">{loadError}</p>}
      {agents
        .filter(
          (agent) =>
            agent.id === selectedAgent &&
            (!agent.backend || agent.backend === "qwenpaw"),
        )
        .map((agent) => (
          <div key={agent.id} className={styles.row}>
            <button
              className={styles.heading}
              onClick={() => setOpen(open === agent.id ? null : agent.id)}
              aria-expanded={open === agent.id}
            >
              <span>{agent.name || agent.id}</span>
              <span className={styles.model}>
                {agent.active_model?.model ||
                  t("thinkingControl.modelSource.global")}
              </span>
              <ChevronDown size={15} />
            </button>
            {open === agent.id && (
              <div className={styles.editor}>
                <div className={styles.choice}>
                  <Select
                    labelRender={({ label }) =>
                      label ?? agent.active_model?.model
                    }
                    showSearch
                    optionFilterProp="label"
                    options={options}
                    value={
                      agent.active_model
                        ? JSON.stringify({
                            provider_id: agent.active_model.provider_id,
                            model: agent.active_model.model,
                          })
                        : undefined
                    }
                    placeholder={t("thinkingControl.modelSource.global")}
                    aria-label={t("agent.model")}
                    loading={busy}
                    disabled={busy}
                    onChange={(value) => void save(agent.id, value)}
                  />
                  <Tooltip title={t("thinkingControl.modelSource.global")}>
                    <button
                      disabled={busy || !agent.active_model}
                      aria-label={t("thinkingControl.modelSource.global")}
                      onClick={() => void save(agent.id)}
                    >
                      <RotateCcw size={16} />
                    </button>
                  </Tooltip>
                </div>
                <AgentModelSettings
                  key={`${agent.id}:${agent.active_model?.provider_id}:${agent.active_model?.model}`}
                  agentId={agent.id}
                  providers={eligible}
                  activeProviderId={
                    agent.active_model?.provider_id ??
                    activeModels?.active_llm?.provider_id
                  }
                  activeModelId={
                    agent.active_model?.model ?? activeModels?.active_llm?.model
                  }
                />
              </div>
            )}
          </div>
        ))}
    </section>
  );
}
