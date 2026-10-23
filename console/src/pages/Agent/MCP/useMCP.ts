import { useCallback, useEffect, useRef, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { MCPAccessPolicy, MCPClientInfo } from "../../../api/types";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import {
  harnessApi,
  type HarnessDiscoveredMCPServer,
} from "../../../api/modules/harness";

type MutationOwner = {
  agentId: string;
  generation: number;
};

export function useMCP() {
  const { t } = useTranslation();
  const { selectedAgent, agents } = useAgentStore();
  const selectedAgentInfo = agents.find((item) => item.id === selectedAgent);
  const selectedBackend = selectedAgentInfo?.backend ?? "qwenpaw";
  const canDiscoverProviderMCP = Boolean(
    selectedAgentInfo?.backend_capabilities?.provider_mcp_discovery,
  );
  const [clients, setClients] = useState<MCPClientInfo[]>([]);
  const [providerServers, setProviderServers] = useState<
    HarnessDiscoveredMCPServer[]
  >([]);
  const [loadingAgent, setLoadingAgent] = useState<string | null>(null);
  const [loadedAgent, setLoadedAgent] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<{
    agentId: string;
    message: string;
  } | null>(null);
  const { message } = useAppMessage();
  const requestGeneration = useRef(0);
  const mutationGeneration = useRef(0);
  const loadedAgentRef = useRef<string | null>(null);
  const agentId = selectedAgent || "default";

  const ownsMutation = useCallback(
    (owner: MutationOwner) =>
      mutationGeneration.current === owner.generation &&
      loadedAgentRef.current === owner.agentId &&
      (useAgentStore.getState().selectedAgent || "default") === owner.agentId,
    [],
  );

  const captureMutationOwner = useCallback((): MutationOwner | null => {
    const owner = {
      agentId,
      generation: mutationGeneration.current,
    };
    return ownsMutation(owner) ? owner : null;
  }, [agentId, ownsMutation]);

  const loadClients = useCallback(async () => {
    const generation = ++requestGeneration.current;
    const requestedAgent = selectedAgent || "default";
    const isCurrentRequest = () =>
      generation === requestGeneration.current &&
      (useAgentStore.getState().selectedAgent || "default") === requestedAgent;

    if (!isCurrentRequest()) return;
    setLoadingAgent(requestedAgent);
    setLoadError(null);
    try {
      const data = await api.listMCPClients(requestedAgent);
      let discoveredServers: HarnessDiscoveredMCPServer[] = [];
      let discoveryWarning = "";
      if (selectedBackend !== "qwenpaw" && canDiscoverProviderMCP) {
        try {
          const discovered = await harnessApi.listMCP(selectedBackend);
          discoveredServers = discovered.servers;
          discoveryWarning = discovered.message ?? "";
        } catch (error) {
          console.warn("Failed to discover Provider MCP servers:", error);
        }
      }
      if (!isCurrentRequest()) return;
      setClients(data);
      setProviderServers(discoveredServers);
      loadedAgentRef.current = requestedAgent;
      setLoadedAgent(requestedAgent);
      if (discoveryWarning) message.warning(discoveryWarning);
    } catch (error) {
      if (!isCurrentRequest()) return;
      console.error("Failed to load MCP clients:", error);
      const errorMessage = t("mcp.loadError");
      setLoadError({ agentId: requestedAgent, message: errorMessage });
      message.error(errorMessage);
    } finally {
      if (isCurrentRequest()) setLoadingAgent(null);
    }
  }, [canDiscoverProviderMCP, message, selectedAgent, selectedBackend, t]);

  useEffect(() => {
    void loadClients();
    return () => {
      requestGeneration.current += 1;
      mutationGeneration.current += 1;
    };
  }, [loadClients]);

  const createClient = useCallback(
    async (
      key: string,
      clientData: {
        name: string;
        description?: string;
        command: string;
        enabled?: boolean;
        transport?: "stdio" | "streamable_http" | "sse";
        url?: string;
        headers?: Record<string, string>;
        args?: string[];
        env?: Record<string, string>;
        cwd?: string;
        http_timeout?: number;
      },
    ) => {
      const owner = captureMutationOwner();
      if (!owner) return false;
      try {
        await api.createMCPClient({
          client_key: key,
          client: clientData,
        });
        if (!ownsMutation(owner)) return false;
        message.success(t("mcp.createSuccess"));
        await loadClients();
        if (!ownsMutation(owner)) return false;
        return true;
      } catch (error) {
        if (!ownsMutation(owner)) return false;
        const errorMsg =
          error instanceof Error ? error.message : t("mcp.createError");
        message.error(errorMsg);
        return false;
      }
    },
    [captureMutationOwner, loadClients, message, ownsMutation, t],
  );

  const updateClient = useCallback(
    async (
      key: string,
      updates: {
        name?: string;
        description?: string;
        command?: string;
        enabled?: boolean;
        transport?: "stdio" | "streamable_http" | "sse";
        url?: string;
        headers?: Record<string, string>;
        args?: string[];
        env?: Record<string, string>;
        cwd?: string;
        http_timeout?: number;
      },
    ) => {
      const owner = captureMutationOwner();
      if (!owner) return false;
      try {
        await api.updateMCPClient(key, updates);
        if (!ownsMutation(owner)) return false;
        setClients((current) =>
          current.map((item) =>
            item.key === key ? { ...item, ...updates } : item,
          ),
        );
        return true;
      } catch (error) {
        if (!ownsMutation(owner)) return false;
        const errorMsg =
          error instanceof Error ? error.message : t("mcp.updateError");
        message.error(errorMsg);
        return false;
      }
    },
    [captureMutationOwner, message, ownsMutation, t],
  );

  const toggleEnabled = useCallback(
    async (client: MCPClientInfo) => {
      const owner = captureMutationOwner();
      if (!owner) return;
      try {
        await api.toggleMCPClient(client.key);
        if (!ownsMutation(owner)) return;
        setClients((current) =>
          current.map((item) =>
            item.key === client.key
              ? { ...item, enabled: !client.enabled }
              : item,
          ),
        );
      } catch {
        if (!ownsMutation(owner)) return;
        message.error(t("mcp.toggleError"));
      }
    },
    [captureMutationOwner, message, ownsMutation, t],
  );

  const deleteClient = useCallback(
    async (client: MCPClientInfo) => {
      const owner = captureMutationOwner();
      if (!owner) return;
      try {
        await api.deleteMCPClient(client.key);
        if (!ownsMutation(owner)) return;
        message.success(t("mcp.deleteSuccess"));
        await loadClients();
        if (!ownsMutation(owner)) return;
      } catch {
        if (!ownsMutation(owner)) return;
        message.error(t("mcp.deleteError"));
      }
    },
    [captureMutationOwner, loadClients, message, ownsMutation, t],
  );

  const updatePolicy = useCallback(
    async (clientKey: string, policy: MCPAccessPolicy) => {
      const owner = captureMutationOwner();
      if (!owner) return false;
      try {
        await api.updateMCPPolicy(clientKey, policy);
        if (!ownsMutation(owner)) return false;
        message.success(t("mcp.access.saveSuccess"));
        await loadClients();
        if (!ownsMutation(owner)) return false;
        return true;
      } catch (error) {
        if (!ownsMutation(owner)) return false;
        const errorMsg =
          error instanceof Error ? error.message : t("mcp.access.saveError");
        message.error(errorMsg);
        return false;
      }
    },
    [captureMutationOwner, loadClients, message, ownsMutation, t],
  );

  const ready = loadedAgent === agentId;
  const error = loadError?.agentId === agentId ? loadError.message : null;
  const loading = loadingAgent === agentId || (!ready && !error);

  return {
    agentId,
    clients,
    providerServers,
    loading,
    error,
    ready,
    createClient,
    updateClient,
    updatePolicy,
    toggleEnabled,
    deleteClient,
    refreshClients: loadClients,
  };
}
