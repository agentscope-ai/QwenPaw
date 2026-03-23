import { Select, message, Badge } from "antd";
import { useEffect, useState } from "react";
import { Bot, Layers, CheckCircle } from "lucide-react";
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
      setAgents(data.agents);
    } catch (error) {
      console.error("Failed to load agents:", error);
      message.error(t("agent.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (value: string) => {
    setSelectedAgent(value);
    message.success(t("agent.switchSuccess"));
  };

  const agentCount = agents?.length ?? 0;

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
            label={
              <div className={styles.selectedAgentLabel}>
                <Bot size={14} strokeWidth={2} />
                <span>{agent.name}</span>
              </div>
            }
          >
            <div className={styles.agentOption}>
              <div className={styles.agentOptionHeader}>
                <div className={styles.agentOptionIcon}>
                  <Bot size={16} strokeWidth={2} />
                </div>
                <div className={styles.agentOptionContent}>
                  <div className={styles.agentOptionName}>
                    <span>{agent.name}</span>
                    {agent.id === selectedAgent && (
                      <CheckCircle
                        size={14}
                        strokeWidth={2}
                        className={styles.activeIndicator}
                      />
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
