import { useState, useEffect } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import type { AgentSummary } from "@/api/types/agents";
import { useAgentStore } from "@/stores/agentStore";

interface UseAgentsReturn {
  agents: AgentSummary[];
  loading: boolean;
  error: Error | null;
  loadAgents: () => Promise<AgentSummary[]>;
  deleteAgent: (agentId: string) => Promise<void>;
}

export function useAgents(): UseAgentsReturn {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { agents, setAgents: updateStoreAgents } = useAgentStore();

  const loadAgents = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.listAgents();
      updateStoreAgents(data.agents);
      return data.agents;
    } catch (err) {
      console.error("Failed to load agents:", err);
      const errorMsg =
        err instanceof Error ? err : new Error(t("agent.loadFailed"));
      setError(errorMsg);
      message.error(t("agent.loadFailed"));
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const deleteAgent = async (agentId: string) => {
    try {
      await agentsApi.deleteAgent(agentId);
      message.success(t("agent.deleteSuccess"));
      await loadAgents();
    } catch (err: any) {
      message.error(err.message || t("agent.deleteFailed"));
      throw err;
    }
  };

  useEffect(() => {
    void loadAgents();
  }, []);

  return {
    agents,
    loading,
    error,
    loadAgents,
    deleteAgent,
  };
}
