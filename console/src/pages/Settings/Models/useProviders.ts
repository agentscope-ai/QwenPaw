import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type { ProviderInfo, ActiveModelsInfo } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";

export function useProviders() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { selectedAgent } = useAgentStore();

  const fetchAll = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setLoading(true);
    }
    setError(null);
    try {
      const [provData, activeData] = await Promise.all([
        api.listProviders(),
        api.getActiveModels({ scope: "global" }),
      ]);
      if (!Array.isArray(provData)) {
        throw new Error(
          "Unexpected API response. Is VITE_API_BASE_URL configured correctly?",
        );
      }
      setProviders(provData);
      if (activeData) setActiveModels(activeData);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to load provider data";
      console.error("Failed to load providers:", err);
      setError(msg);
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll, selectedAgent]);

  return {
    providers,
    activeModels,
    loading,
    error,
    fetchAll,
  };
}
