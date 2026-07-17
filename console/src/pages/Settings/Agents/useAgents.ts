import { useCallback, useEffect, useRef, useState } from "react";
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
  pinAgent: (agentId: string, pinned: boolean) => Promise<void>;
  setAgents: (agents: AgentSummary[]) => void;
}

export function useAgents(): UseAgentsReturn {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const {
    agents,
    setAgents: updateStoreAgents,
    refreshAgents,
  } = useAgentStore();
  const { message } = useAppMessage();
  const messageRef = useRef(message);
  const translationRef = useRef(t);
  messageRef.current = message;
  translationRef.current = t;

  const setAgentsState = useCallback(
    (nextAgents: AgentSummary[]) => {
      updateStoreAgents(nextAgents);
    },
    [updateStoreAgents],
  );

  const fetchAgents = useCallback(
    async (showLoading: boolean, reportError: boolean) => {
      if (showLoading) {
        setLoading(true);
      }
      setError(null);
      try {
        await refreshAgents();
      } catch (err) {
        console.error("Failed to load agents:", err);
        const errorMsg =
          err instanceof Error
            ? err
            : new Error(translationRef.current("agent.loadFailed"));
        setError(errorMsg);
        if (reportError) {
          messageRef.current.error(translationRef.current("agent.loadFailed"));
        }
      } finally {
        if (showLoading) {
          setLoading(false);
        }
      }
    },
    [refreshAgents],
  );

  const loadAgents = useCallback(() => fetchAgents(true, true), [fetchAgents]);

  const deleteAgent = async (agentId: string) => {
    try {
      await agentsApi.deleteAgent(agentId);
      message.success(t("agent.deleteSuccess"));
      await fetchAgents(false, false);
    } catch (err: unknown) {
      message.error(
        err instanceof Error ? err.message : t("agent.deleteFailed"),
      );
      throw err;
    }
  };

  const toggleAgent = async (agentId: string, enabled: boolean) => {
    if (enabled) {
      setAgentsState(
        agents.map((agent) =>
          agent.id === agentId
            ? {
                ...agent,
                enabled: true,
                startup_status: "starting",
              }
            : agent,
        ),
      );
    }

    try {
      await agentsApi.toggleAgentEnabled(agentId, enabled);
      const successMsg = enabled
        ? t("agent.enableSuccess")
        : t("agent.disableSuccess");
      message.success(successMsg);
      await fetchAgents(false, false);
    } catch (err: unknown) {
      await fetchAgents(false, false);
      message.error(
        err instanceof Error ? err.message : t("agent.toggleFailed"),
      );
      throw err;
    }
  };

  const pinAgent = async (agentId: string, pinned: boolean) => {
    setAgentsState(
      agents.map((agent) =>
        agent.id === agentId ? { ...agent, pinned } : agent,
      ),
    );
    try {
      await agentsApi.setAgentPinned(agentId, pinned);
      message.success(pinned ? t("agent.pinSuccess") : t("agent.unpinSuccess"));
      await fetchAgents(false, false);
    } catch (err: unknown) {
      await fetchAgents(false, false);
      message.error(err instanceof Error ? err.message : t("agent.pinFailed"));
      throw err;
    }
  };

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  return {
    agents,
    loading,
    error,
    loadAgents,
    deleteAgent,
    toggleAgent,
    pinAgent,
    setAgents: setAgentsState,
  };
}
