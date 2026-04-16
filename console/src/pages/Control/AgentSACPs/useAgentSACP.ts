import { useEffect, useState } from "react";
import { message } from "@agentscope-ai/design";
import type {
  AgentSACPConfig,
  CreateAgentSACPRequest,
  UpdateAgentSACPRequest,
} from "@/api/types/agent_sacp";
import { agentSACPApi } from "@/api/modules/agent_sacp";
import { agentsApi } from "@/api/modules/agents";
import type { AgentSummary } from "@/api/types/agents";
import { channelApi } from "@/api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

export function useAgentSACP() {
  const { selectedAgent } = useAgentStore();
  const [agents, setAgents] = useState<AgentSACPConfig[]>([]);
  const [internalAgents, setInternalAgents] = useState<AgentSummary[]>([]);
  const [globalAuthKey, setGlobalAuthKey] = useState<string>("");
  const [loading, setLoading] = useState(false);
  // Channel enabled status per agent (fetched from channel API, NOT part of AgentSACPConfig)
  const [channelEnabledMap, setChannelEnabledMap] = useState<
    Record<string, boolean>
  >({});

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const data = await agentSACPApi.getAgents();
      if (data) {
        setAgents(data as AgentSACPConfig[]);
        // Fetch channel_enabled for internal agents
        const map: Record<string, boolean> = {};
        await Promise.all(
          (data as AgentSACPConfig[]).map(async (agent) => {
            if (agent.is_internal && agent.internal_agent_id) {
              try {
                const cfg = await channelApi.getChannelConfig(
                  "sacp",
                  agent.internal_agent_id,
                );
                map[agent.id] = cfg.enabled ?? false;
              } catch {
                map[agent.id] = false;
              }
            }
          }),
        );
        setChannelEnabledMap(map);
      }
    } catch (error) {
      console.error("Failed to load Agent SACP agents", error);
      message.error("Failed to load Agent SACP Agents");
    } finally {
      setLoading(false);
    }
  };

  const fetchInternalAgents = async () => {
    try {
      const data = await agentsApi.listAgents();
      if (data && data.agents) {
        setInternalAgents(data.agents);
      }
    } catch (error) {
      console.error("Failed to load internal agents", error);
    }
  };

  const fetchGlobalAuthKey = async () => {
    try {
      const settings = await agentSACPApi.getSettings();
      if (settings) {
        setGlobalAuthKey(settings.global_internal_auth_key || "");
      }
    } catch (error) {
      console.error("Failed to load global auth key", error);
    }
  };

  const updateGlobalAuthKey = async (key: string) => {
    try {
      await agentSACPApi.updateSettings({ global_internal_auth_key: key });
      setGlobalAuthKey(key);
      message.success("Global auth key updated");
      return true;
    } catch (error) {
      console.error("Failed to update global auth key", error);
      message.error("Failed to update global auth key");
      return false;
    }
  };

  useEffect(() => {
    let mounted = true;

    const loadAgents = async () => {
      await fetchAgents();
    };

    if (mounted) {
      loadAgents();
      fetchInternalAgents();
      fetchGlobalAuthKey();
    }

    return () => {
      mounted = false;
    };
  }, [selectedAgent]);

  const createAgent = async (values: CreateAgentSACPRequest) => {
    const optimisticAgent: AgentSACPConfig = {
      id: `temp-${Date.now()}`,
      name: values.name,
      description: values.description ?? "",
      url: values.url,
      auth_key: values.auth_key,
      is_internal: values.is_internal ?? true,
      internal_agent_id: values.internal_agent_id ?? null,
      health_status: "unknown",
      last_health_check: null,
      last_health_error: null,
      consecutive_failures: 0,
      health_check_enabled: values.health_check_enabled ?? true,
      health_check_interval: values.health_check_interval ?? 300,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    setAgents((prev) => [optimisticAgent, ...prev]);

    try {
      const created = await agentSACPApi.createAgent(values);
      setAgents((prev) =>
        prev.map((agent) =>
          agent.id === optimisticAgent.id
            ? (created as AgentSACPConfig)
            : agent,
        ),
      );
      message.success("Created successfully");
      return true;
    } catch (error) {
      console.error("Failed to create Agent SACP agent", error);
      setAgents((prev) =>
        prev.filter((agent) => agent.id !== optimisticAgent.id),
      );
      message.error("Failed to save");
      return false;
    }
  };

  const updateAgent = async (
    agentId: string,
    values: UpdateAgentSACPRequest,
  ) => {
    const original = agents.find((agent) => agent.id === agentId);
    const optimisticUpdate: AgentSACPConfig = {
      ...(original as AgentSACPConfig),
      name: values.name ?? original?.name ?? "",
      description: values.description ?? original?.description ?? "",
      url: values.url ?? original?.url ?? "",
      auth_key: values.auth_key ?? original?.auth_key ?? "",
      is_internal: values.is_internal ?? original?.is_internal ?? true,
      internal_agent_id:
        values.internal_agent_id !== undefined
          ? values.internal_agent_id
          : original?.internal_agent_id ?? null,
      health_check_enabled:
        values.health_check_enabled ?? original?.health_check_enabled ?? true,
      health_check_interval:
        values.health_check_interval ?? original?.health_check_interval ?? 300,
      updated_at: new Date().toISOString(),
    };
    setAgents((prev) =>
      prev.map((agent) => (agent.id === agentId ? optimisticUpdate : agent)),
    );

    try {
      const updated = await agentSACPApi.updateAgent(agentId, values);
      setAgents((prev) =>
        prev.map((agent) =>
          agent.id === agentId ? (updated as AgentSACPConfig) : agent,
        ),
      );
      message.success("Updated successfully");
      return true;
    } catch (error) {
      console.error("Failed to update Agent SACP agent", error);
      if (original) {
        setAgents((prev) =>
          prev.map((agent) => (agent.id === agentId ? original : agent)),
        );
      }
      message.error("Failed to save");
      return false;
    }
  };

  const deleteAgent = async (agentId: string) => {
    const originalIndex = agents.findIndex((agent) => agent.id === agentId);
    const original = agents[originalIndex];
    setAgents((prev) => prev.filter((agent) => agent.id !== agentId));

    try {
      await agentSACPApi.deleteAgent(agentId);
      message.success("Deleted successfully");
      return true;
    } catch (error) {
      console.error("Failed to delete Agent SACP agent", error);
      if (original) {
        setAgents((prev) => {
          const next = [...prev];
          next.splice(originalIndex, 0, original);
          return next;
        });
      }
      message.error("Failed to delete");
      return false;
    }
  };

  const healthCheckAgent = async (agentId: string) => {
    const original = agents.find((agent) => agent.id === agentId);

    if (original) {
      setAgents((prev) =>
        prev.map((agent) =>
          agent.id === agentId
            ? {
                ...agent,
                health_status: "unknown",
                last_health_error: null,
              }
            : agent,
        ),
      );
    }

    try {
      const result = await agentSACPApi.healthCheckAgent(agentId);
      setAgents((prev) =>
        prev.map((agent) =>
          agent.id === agentId
            ? {
                ...agent,
                health_status: result.status,
                last_health_check: result.checked_at,
                last_health_error: result.error,
              }
            : agent,
        ),
      );
      message.success("Health check completed");
      return true;
    } catch (error) {
      console.error("Failed to health check Agent SACP agent", error);
      if (original) {
        setAgents((prev) =>
          prev.map((agent) => (agent.id === agentId ? original : agent)),
        );
      }
      message.error("Failed to execute");
      return false;
    }
  };

  const toggleChannel = async (agentId: string, enabled: boolean) => {
    const agent = agents.find((a) => a.id === agentId);
    if (!agent || !agent.internal_agent_id) {
      message.error("Invalid agent");
      return false;
    }

    // Optimistic update
    setChannelEnabledMap((prev) => ({ ...prev, [agentId]: enabled }));

    try {
      const currentConfig = await channelApi.getChannelConfig(
        "sacp",
        agent.internal_agent_id,
      );
      await channelApi.updateChannelConfig(
        "sacp",
        { ...currentConfig, enabled },
        agent.internal_agent_id,
      );
      message.success(
        enabled ? "SACP channel enabled" : "SACP channel disabled",
      );
      return true;
    } catch (error) {
      console.error("Failed to toggle SACP channel", error);
      // Revert optimistic update
      setChannelEnabledMap((prev) => ({ ...prev, [agentId]: !enabled }));
      message.error(`Failed to ${enabled ? "enable" : "disable"} channel`);
      return false;
    }
  };

  return {
    agents,
    internalAgents,
    globalAuthKey,
    loading,
    channelEnabledMap,
    createAgent,
    updateAgent,
    deleteAgent,
    healthCheckAgent,
    toggleChannel,
    updateGlobalAuthKey,
  };
}
