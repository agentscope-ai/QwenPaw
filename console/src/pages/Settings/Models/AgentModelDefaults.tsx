import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { ModelChoice } from "../../Chat/ModelSelector/ModelChoice";
import { useEffect, useState } from "react";
import { Tooltip } from "antd";
import { RotateCcw } from "lucide-react";
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
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  useEffect(() => {
    void refresh().catch((error) => setLoadError(String(error)));
  }, [refresh]);
  const eligible = buildEligibleProviders(providers);
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
    <InteractiveCard
      as="section"
      tilt={0}
      className={styles.section}
      aria-label={t("models.agentDefaults")}
    >
      {loadError && <p role="alert">{loadError}</p>}
      {agents
        .filter(
          (agent) =>
            agent.id === selectedAgent &&
            (!agent.backend || agent.backend === "qwenpaw"),
        )
        .map((agent) => (
          <div key={agent.id} className={styles.row}>
            <div className={styles.editor}>
              <div className={styles.choice}>
                <span>{t("agent.model")}</span>
                <ModelChoice
                  value={agent.active_model}
                  label={
                    agent.active_model?.model ||
                    t("thinkingControl.modelSource.global")
                  }
                  disabled={busy}
                  onChange={(value) =>
                    void save(agent.id, JSON.stringify(value))
                  }
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
                expanded
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
          </div>
        ))}
    </InteractiveCard>
  );
}
