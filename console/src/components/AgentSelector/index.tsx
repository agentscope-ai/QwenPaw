import { Select, message, Badge, Tag } from "antd";
import { useEffect, useState } from "react";
import { Bot, Layers, CheckCircle, EyeOff } from "lucide-react";
import { useAgentStore } from "../../stores/agentStore";
import { agentsApi } from "../../api/modules/agents";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

export default function AgentSelector() {
  const { t } = useTranslation();
  const { selectedAgent, agents, setSelectedAgent, setAgents } =
    useAgentStore();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      setLoading(true);
      const data = await agentsApi.listAgents();
      // Sort agents: enabled first, disabled last
      const sortedAgents = [...data.agents].sort((a, b) => {
        if (a.enabled === b.enabled) return 0;
        return a.enabled ? -1 : 1;
      });
      setAgents(sortedAgents);
    } catch (error) {
      console.error("Failed to load agents:", error);
      message.error(t("agent.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (value: string) => {
    const targetAgent = agents?.find((a) => a.id === value);

    // Prevent switching to disabled agent
    if (targetAgent && !targetAgent.enabled) {
      message.warning(t("agent.cannotSwitchToDisabled"));
      return;
    }

    setSelectedAgent(value);
    message.success(t("agent.switchSuccess"));
  };

  // Check if current agent is disabled, auto-switch to default
  useEffect(() => {
    const currentAgent = agents?.find((a) => a.id === selectedAgent);
    if (currentAgent && !currentAgent.enabled) {
      setSelectedAgent("default");
      message.warning(t("agent.currentAgentDisabled"));
    }
  }, [agents, selectedAgent, setSelectedAgent, t]);

  // Count only enabled agents for badge
  const enabledCount = agents?.filter((a) => a.enabled).length ?? 0;
  const agentCount = enabledCount;

  return (
    <div className={styles.agentSelectorWrapper}>
      <div className={styles.agentSelectorLabel}>
        <Layers size={14} strokeWidth={2} />
        <span>{t("agent.currentWorkspace")}</span>
      </div>
      <Select
        value={selectedAgent}
        onChange={handleChange}
        loading={loading}
        className={styles.agentSelector}
        placeholder={t("agent.selectAgent")}
        optionLabelProp="label"
        popupClassName={styles.agentSelectorDropdown}
        suffixIcon={
          <div className={styles.agentSelectorSuffix}>
            <Badge count={agentCount} showZero className={styles.agentBadge} />
          </div>
        }
      >
        {agents?.map((agent) => (
          <Select.Option
            key={agent.id}
            value={agent.id}
            disabled={!agent.enabled}
            label={
              <div className={styles.selectedAgentLabel}>
                <Bot size={14} strokeWidth={2} />
                <span>{agent.name}</span>
                {!agent.enabled && <EyeOff size={12} strokeWidth={2} />}
              </div>
            }
          >
            <div
              className={styles.agentOption}
              style={{ opacity: agent.enabled ? 1 : 0.5 }}
            >
              <div className={styles.agentOptionHeader}>
                <div className={styles.agentOptionIcon}>
                  <Bot size={16} strokeWidth={2} />
                </div>
                <div className={styles.agentOptionContent}>
                  <div className={styles.agentOptionName}>
                    <span className={styles.agentOptionNameText}>
                      {agent.name}
                    </span>
                    {agent.id === selectedAgent && (
                      <CheckCircle
                        size={14}
                        strokeWidth={2}
                        className={styles.activeIndicator}
                      />
                    )}
                    {!agent.enabled && (
                      <Tag color="error" style={{ margin: 0 }}>
                        {t("agent.disabled")}
                      </Tag>
                    )}
                  </div>
                  {agent.description && (
                    <div className={styles.agentOptionDescription}>
                      {agent.description}
                    </div>
                  )}
                </div>
              </div>
              <div className={styles.agentOptionId}>ID: {agent.id}</div>
            </div>
          </Select.Option>
        ))}
      </Select>
    </div>
  );
}
