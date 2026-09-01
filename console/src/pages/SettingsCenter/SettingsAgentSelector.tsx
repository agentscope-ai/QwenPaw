import { Select } from "antd";
import { Bot } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import { useAgentStore } from "@/stores/agentStore";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import { isAgentAvailableInChat } from "@/utils/agentVisibility";
import styles from "./index.module.less";

export default function SettingsAgentSelector() {
  const { t } = useTranslation();
  const { selectedAgent, agents, setSelectedAgent, refreshAgents } =
    useAgentStore();
  const availableAgents = useMemo(
    () =>
      agents.filter((agent) => agent.enabled && isAgentAvailableInChat(agent)),
    [agents],
  );
  const currentAgent = availableAgents.find(
    (agent) => agent.id === selectedAgent,
  );

  useEffect(() => {
    if (agents.length === 0) void refreshAgents().catch(() => {});
  }, [agents.length, refreshAgents]);

  return (
    <div className={styles.settingsAgentSelector}>
      <span className={styles.settingsAgentSelectorLabel}>
        {t("agent.currentWorkspace")}
      </span>
      <Select
        aria-label={t("agent.selectAgent")}
        className={styles.settingsAgentSelect}
        value={selectedAgent}
        onChange={(agentId) => setSelectedAgent(agentId)}
        options={availableAgents.map((agent) => ({
          value: agent.id,
          label: (
            <span className={styles.settingsAgentOption}>
              <AgentStatusIndicator
                status={agent.startup_status}
                enabled={agent.enabled}
              />
              <Bot size={15} />
              <span>{getAgentDisplayName(agent, t)}</span>
            </span>
          ),
        }))}
      />
      <span className={styles.settingsAgentBackend}>
        {currentAgent?.backend || selectedAgent}
      </span>
    </div>
  );
}
