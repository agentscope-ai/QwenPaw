import { useCallback, useEffect, useState } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { MCPAccessPolicy, MCPClientInfo } from "../../../api/types";
import type { MCPClientUpdateRequest } from "../../../api/types";
import { useSkillScope } from "../../../api/skillScope";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import {
  harnessApi,
  type HarnessDiscoveredMCPServer,
} from "../../../api/modules/harness";

export function useMCP() {
  const { t } = useTranslation();
  const { selectedAgent, agents } = useAgentStore();
  const scope = useSkillScope(selectedAgent);
  const apiContext = { agentId: scope.agentId, signal: scope.signal };
  const selectedAgentInfo = agents.find((item) => item.id === selectedAgent);
  const selectedBackend = selectedAgentInfo?.backend ?? "qwenpaw";
  const canDiscoverProviderMCP = Boolean(
    selectedAgentInfo?.backend_capabilities?.provider_mcp_discovery,
  );
  const [clients, setClients] = useState<MCPClientInfo[]>([]);
  const [providerServers, setProviderServers] = useState<
    HarnessDiscoveredMCPServer[]
  >([]);
  const [loading, setLoading] = useState(false);
  const { message } = useAppMessage();

  const loadClients = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listMCPClients(apiContext);
      if (!scope.current()) return;
      setClients(data);
      if (selectedBackend !== "qwenpaw" && canDiscoverProviderMCP) {
        try {
          const discovered = await harnessApi.listMCP(selectedBackend);
          if (!scope.current()) return;
          setProviderServers(discovered.servers);
          if (discovered.message) {
            message.warning(discovered.message);
          }
        } catch (error) {
          if (!scope.current()) return;
          console.warn("Failed to discover Provider MCP servers:", error);
          setProviderServers([]);
        }
      } else {
        setProviderServers([]);
      }
    } catch (error) {
      if (!scope.current()) return;
      console.error("Failed to load MCP clients:", error);
      message.error(t("mcp.loadError"));
    } finally {
      if (scope.current()) setLoading(false);
    }
  }, [canDiscoverProviderMCP, message, selectedBackend, t, scope]);

  useEffect(() => {
    setClients([]);
    setProviderServers([]);
    setLoading(false);
    void loadClients();
  }, [loadClients, selectedAgent, scope.key]);

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
      },
    ) => {
      try {
        if (!scope.canEdit) return false;
        await api.createMCPClient({
          client_key: key,
          client: clientData,
        }, apiContext);
        if (!scope.current()) return false;
        message.success(t("mcp.createSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        if (!scope.current()) return false;
        const errorMsg = error?.message || t("mcp.createError");
        message.error(errorMsg);
        return false;
      }
    },
    [message, t, loadClients, scope],
  );

  const updateClient = useCallback(
    async (
      key: string,
      updates: MCPClientUpdateRequest,
      expectedRevision?: number,
    ) => {
      try {
        if (!scope.canEdit) return false;
        await api.updateMCPClient(
          key,
          { ...updates, expected_revision: expectedRevision },
          apiContext,
        );
        if (!scope.current()) return false;
        message.success(t("mcp.updateSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        if (!scope.current()) return false;
        const errorMsg = error?.message || t("mcp.updateError");
        message.error(errorMsg);
        return false;
      }
    },
    [message, t, loadClients, scope],
  );

  const toggleEnabled = useCallback(
    async (client: MCPClientInfo) => {
      try {
        if (!scope.canEdit) return;
        await api.toggleMCPClient(client.key, client.revision, apiContext);
        if (!scope.current()) return;
        message.success(
          client.enabled ? t("mcp.disableSuccess") : t("mcp.enableSuccess"),
        );
        await loadClients();
      } catch (error) {
        if (!scope.current()) return;
        message.error(t("mcp.toggleError"));
      }
    },
    [message, t, loadClients, scope],
  );

  const deleteClient = useCallback(
    async (client: MCPClientInfo) => {
      try {
        if (!scope.canEdit) return;
        await api.deleteMCPClient(client.key, client.revision, apiContext);
        if (!scope.current()) return;
        message.success(t("mcp.deleteSuccess"));
        await loadClients();
      } catch (error) {
        if (!scope.current()) return;
        message.error(t("mcp.deleteError"));
      }
    },
    [message, t, loadClients, scope],
  );

  const updatePolicy = useCallback(
    async (clientKey: string, policy: MCPAccessPolicy, expectedRevision?: number) => {
      try {
        if (!scope.canEdit) return false;
        await api.updateMCPPolicy(clientKey, policy, expectedRevision, apiContext);
        if (!scope.current()) return false;
        message.success(t("mcp.access.saveSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        if (!scope.current()) return false;
        const errorMsg = error?.message || t("mcp.access.saveError");
        message.error(errorMsg);
        return false;
      }
    },
    [message, t, loadClients, scope],
  );

  return {
    clients,
    providerServers,
    loading,
    canEdit: scope.canEdit,
    scopeKey: scope.key,
    createClient,
    updateClient,
    updatePolicy,
    toggleEnabled,
    deleteClient,
    refreshClients: loadClients,
  };
}
