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
  const agentById = useMemo(
    () => new Map(availableAgents.map((agent) => [agent.id, agent])),
    [availableAgents],
  );

  useEffect(() => {
    if (agents.length === 0) void refreshAgents().catch(() => {});
  }, [agents.length, refreshAgents]);

  return (
    <div className={styles.settingsAgentSelector}>
      <Select
        aria-label={t("agent.selectAgent")}
        className={styles.settingsAgentSelect}
        value={selectedAgent}
        onChange={(agentId) => setSelectedAgent(agentId)}
        options={availableAgents.map((agent) => ({
          value: agent.id,
          label: getAgentDisplayName(agent, t),
        }))}
        labelRender={({ value, label }) => {
          const agent = agentById.get(String(value));
          return (
            <span className={styles.settingsAgentOptionIdentity}>
              <AgentStatusIndicator
                status={agent?.startup_status}
                enabled={agent?.enabled}
              />
              <Bot size={15} />
              <span>{label}</span>
            </span>
          );
        }}
        optionRender={({ value, label }) => {
          const agent = agentById.get(String(value));
          return (
            <span className={styles.settingsAgentOption}>
              <span className={styles.settingsAgentOptionIdentity}>
                <AgentStatusIndicator
                  status={agent?.startup_status}
                  enabled={agent?.enabled}
                />
                <Bot size={15} />
                <span>{label}</span>
              </span>
              {agent?.backend && (
                <small className={styles.settingsAgentOptionBackend}>
                  {agent.backend}
                </small>
              )}
            </span>
          );
        }}
      />
    </div>
  );
}
