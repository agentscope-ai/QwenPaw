import { useCallback, useEffect, useState } from "react";
import { message } from "@agentscope-ai/design";
import api from "../../../api";
import type { MCPClientInfo } from "../../../api/types";
import { useTranslation } from "react-i18next";

export function useMCP() {
  const { t } = useTranslation();
  const [clients, setClients] = useState<MCPClientInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [queuedRefreshKeys, setQueuedRefreshKeys] = useState<string[]>([]);
  const [refreshingKeys, setRefreshingKeys] = useState<string[]>([]);

  const loadClients = useCallback(async (options?: { silent?: boolean; showLoading?: boolean }) => {
    const { silent = false, showLoading = true } = options ?? {};
    if (showLoading) {
      setLoading(true);
    }
    try {
      const data = await api.listMCPClients();
      setClients(data);
    } catch (error) {
      console.error("Failed to load MCP clients:", error);
      if (!silent) {
        message.error(t("mcp.loadError"));
      }
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, [t]);

  useEffect(() => {
    loadClients();
  }, [loadClients]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      loadClients({ silent: true, showLoading: false });
    }, 15000);

    return () => window.clearInterval(intervalId);
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
      },
    ) => {
      try {
        await api.createMCPClient({
          client_key: key,
          client: clientData,
        });
        message.success(t("mcp.createSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        const errorMsg = error?.message || t("mcp.createError");
        message.error(errorMsg);
        return false;
      }
    },
    [t, loadClients],
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
      },
    ) => {
      try {
        await api.updateMCPClient(key, updates);
        message.success(t("mcp.updateSuccess"));
        await loadClients();
        return true;
      } catch (error: any) {
        const errorMsg = error?.message || t("mcp.updateError");
        message.error(errorMsg);
        return false;
      }
    },
    [t, loadClients],
  );

  const toggleEnabled = useCallback(
    async (client: MCPClientInfo) => {
      try {
        await api.toggleMCPClient(client.key);
        message.success(
          client.enabled ? t("mcp.disableSuccess") : t("mcp.enableSuccess"),
        );
        await loadClients();
      } catch (error) {
        message.error(t("mcp.toggleError"));
      }
    },
    [t, loadClients],
  );

  const deleteClient = useCallback(
    async (client: MCPClientInfo) => {
      try {
        await api.deleteMCPClient(client.key);
        message.success(t("mcp.deleteSuccess"));
        await loadClients();
      } catch (error) {
        message.error(t("mcp.deleteError"));
      }
    },
    [t, loadClients],
  );

  const refreshClients = useCallback(async () => {
    await loadClients({ silent: true, showLoading: false });
  }, [loadClients]);

  const refreshStatuses = useCallback(async () => {
    const targetKeys = clients
      .filter((client) => client.enabled)
      .map((client) => client.key);

    if (targetKeys.length === 0) {
      await refreshClients();
      return;
    }

    setQueuedRefreshKeys(targetKeys);
    setRefreshingKeys([]);

    for (const key of targetKeys) {
      setQueuedRefreshKeys((current) => current.filter((item) => item !== key));
      setRefreshingKeys((current) => [...current, key]);

      try {
        const updatedClient = await api.refreshMCPClientStatus(key);
        setClients((current) =>
          current.map((client) =>
            client.key === key ? updatedClient : client,
          ),
        );
      } catch (error) {
        console.error(`Failed to refresh MCP client status for ${key}:`, error);
      } finally {
        setRefreshingKeys((current) =>
          current.filter((item) => item !== key),
        );
      }
    }

    setQueuedRefreshKeys([]);
    await refreshClients();
  }, [clients, refreshClients]);

  return {
    clients,
    loading,
    refreshClients,
    refreshStatuses,
    queuedRefreshKeys,
    refreshingKeys,
    createClient,
    updateClient,
    toggleEnabled,
    deleteClient,
  };
}
