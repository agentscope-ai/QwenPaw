import { useState, useEffect } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import type { AgentSummary } from "@/api/types/agents";
import { useAgentStore } from "@/stores/agentStore";

interface UseAgentsReturn {
  agents: AgentSummary[];
  loading: boolean;
  error: Error | null;
  loadAgents: () => Promise<void>;
  deleteAgent: (agentId: string) => Promise<void>;
  toggleAgent: (agentId: string, enabled: boolean) => Promise<void>;
  setAgents: (agents: AgentSummary[]) => void;
}

export function useAgents(): UseAgentsReturn {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const { setAgents: updateStoreAgents } = useAgentStore();
  const { message } = useAppMessage();

  const setAgentsState = (nextAgents: AgentSummary[]) => {
    setAgents(nextAgents);
    updateStoreAgents(nextAgents);
  };

  const loadAgents = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentsApi.listAgents();
      setAgentsState(data.agents);
    } catch (err) {
      console.error("Failed to load agents:", err);
      const errorMsg =
        err instanceof Error ? err : new Error(t("agent.loadFailed"));
      setError(errorMsg);
      message.error(t("agent.loadFailed"));
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

  const toggleAgent = async (agentId: string, enabled: boolean) => {
    try {
      await agentsApi.toggleAgentEnabled(agentId, enabled);
      const successMsg = enabled
        ? t("agent.enableSuccess")
        : t("agent.disableSuccess");
      message.success(successMsg);
      await loadAgents();
    } catch (err: any) {
      message.error(err.message || t("agent.toggleFailed"));
      throw err;
    }
  };

  useEffect(() => {
    loadAgents();
  }, []);

  return {
    agents,
    loading,
    error,
    loadAgents,
    deleteAgent,
    toggleAgent,
    setAgents: setAgentsState,
  };
}
